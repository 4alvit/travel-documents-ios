import Foundation
import Observation
import StoreKit

/// The App Store's verified transaction history is the only source of Pro rights.
/// StoreKit maintains its own on-device history for offline access; an editable
/// UserDefaults flag is deliberately not used as an entitlement cache.
@MainActor
@Observable
final class PurchaseManager {
    static let productID = "com.4alvit.tripfolio.pro"

    private(set) var isPro = false
    private(set) var displayPrice: String?
    private(set) var statusMessage: String?
    private(set) var isBusy = false

    @ObservationIgnored private var product: Product?
    @ObservationIgnored private var updatesTask: Task<Void, Never>?
    @ObservationIgnored private var entitlementRevision: UInt64 = 0

    init() {
        updatesTask = Task { [weak self] in
            for await result in StoreKit.Transaction.updates {
                guard !Task.isCancelled else { return }
                await self?.receive(result)
            }
        }
    }

    deinit {
        updatesTask?.cancel()
    }

    /// Safe to repeat on foreground entry. Reading local entitlements does not
    /// ask for an Apple Account login or require fetching a product price.
    func load() async {
        await refreshEntitlements()
        guard !isBusy else { return }
        isBusy = true
        defer { isBusy = false }
        do {
            try await loadProduct()
        } catch {
            statusMessage = L10n.service("services.purchase.priceUnavailable", defaultValue: "The App Store price is unavailable. Try again when connected. Your existing documents remain available.")
        }
    }

    func purchase() async {
        guard !isBusy else { return }
        isBusy = true
        statusMessage = nil
        defer { isBusy = false }

        guard AppStore.canMakePayments else {
            statusMessage = L10n.service("services.purchase.notAllowed", defaultValue: "Purchases are not allowed on this device. Check its Screen Time or account restrictions.")
            return
        }

        do {
            if product == nil { try await loadProduct() }
            guard let product else { throw PurchaseError.unavailable }
            switch try await product.purchase() {
            case .success(let result):
                guard case .verified(let transaction) = result,
                      transaction.productID == Self.productID,
                      transaction.productType == .nonConsumable else {
                    await refreshEntitlements()
                    statusMessage = L10n.service("services.purchase.unverified", defaultValue: "The App Store could not verify this purchase. No new Pro access was granted. Try Restore Purchases.")
                    return
                }
                await refreshEntitlements()
                await transaction.finish()
                statusMessage = isPro
                    ? L10n.service("services.purchase.ready", defaultValue: "TripDocket Pro is ready. Thank you!")
                    : L10n.service("services.purchase.noEntitlement", defaultValue: "The purchase did not provide an active Pro entitlement. Try Restore Purchases.")
            case .pending:
                statusMessage = L10n.service("services.purchase.pending", defaultValue: "Your purchase is awaiting approval. Pro unlocks when the App Store confirms it.")
            case .userCancelled:
                statusMessage = L10n.service("services.purchase.cancelledFree", defaultValue: "Purchase cancelled. You can continue using the free features.")
            @unknown default:
                statusMessage = L10n.service("services.purchase.unknownState", defaultValue: "The App Store returned an unknown purchase state. Try Restore Purchases before purchasing again.")
            }
        } catch StoreKitError.userCancelled {
            statusMessage = L10n.service("services.purchase.cancelled", defaultValue: "Purchase cancelled.")
        } catch {
            statusMessage = L10n.service("services.purchase.failed", defaultValue: "The purchase could not be completed. Check your connection and App Store account, then try again.")
        }
    }

    /// Explicit user action only: AppStore.sync can show an account prompt.
    func restore() async {
        guard !isBusy else { return }
        isBusy = true
        statusMessage = nil
        defer { isBusy = false }
        do {
            try await AppStore.sync()
            await refreshEntitlements()
            statusMessage = isPro
                ? L10n.service("services.purchase.restore.completed", defaultValue: "TripDocket Pro purchases restored.")
                : L10n.service("services.purchase.restore.notFound", defaultValue: "No active TripDocket Pro purchase was found for this App Store account.")
        } catch StoreKitError.userCancelled {
            statusMessage = L10n.service("services.purchase.restore.cancelled", defaultValue: "Restore cancelled.")
        } catch {
            // A failed network sync must not wipe an already verified local right.
            await refreshEntitlements()
            statusMessage = L10n.service("services.purchase.restore.failed", defaultValue: "Could not sync with the App Store. Existing verified access and your documents remain available. Try again when connected.")
        }
    }

    private func loadProduct() async throws {
        let products = try await Product.products(for: [Self.productID])
        guard let available = products.first(where: {
            $0.id == Self.productID && $0.type == .nonConsumable
        }) else { throw PurchaseError.unavailable }
        product = available
        displayPrice = available.displayPrice
    }

    private func refreshEntitlements() async {
        entitlementRevision &+= 1
        let revision = entitlementRevision
        var hasPro = false
        var verificationFailed = false
        for await result in StoreKit.Transaction.currentEntitlements {
            switch result {
            case .verified(let transaction):
                if transaction.productID == Self.productID,
                   transaction.productType == .nonConsumable,
                   transaction.revocationDate == nil,
                   !transaction.isUpgraded {
                    hasPro = true
                }
            case .unverified(let transaction, _):
                if transaction.productID == Self.productID { verificationFailed = true }
            }
        }
        // An older asynchronous scan cannot overwrite a newer refund/update scan.
        guard revision == entitlementRevision else { return }
        isPro = hasPro
        if verificationFailed && !hasPro {
            statusMessage = L10n.service("services.purchase.entitlementUnverified", defaultValue: "Your Pro purchase could not be verified. Try Restore Purchases when connected. Your saved documents remain available.")
        }
    }

    private func receive(_ result: VerificationResult<StoreKit.Transaction>) async {
        switch result {
        case .verified(let transaction):
            guard transaction.productID == Self.productID else { return }
            if transaction.revocationDate != nil {
                // Remove the known revoked grant immediately. The scan below
                // may still find a later, valid repurchase of the same product.
                entitlementRevision &+= 1
                isPro = false
            }
            await refreshEntitlements()
            await transaction.finish()
            if transaction.revocationDate != nil && !isPro {
                // Refunds/revocations restrict future Pro additions, never reads,
                // deletion, basic export, or recovery of an existing library.
                statusMessage = L10n.service("services.purchase.revoked", defaultValue: "Pro access was revoked by the App Store. Your existing documents, basic export, and recovery remain available.")
            } else if isPro {
                statusMessage = L10n.service("services.purchase.active", defaultValue: "TripDocket Pro is active.")
            }
        case .unverified(let transaction, _):
            guard transaction.productID == Self.productID else { return }
            await refreshEntitlements()
            statusMessage = L10n.service("services.purchase.updateUnverified", defaultValue: "An App Store update could not be verified. Try Restore Purchases.")
        }
    }

    private enum PurchaseError: Error {
        case unavailable
    }
}
