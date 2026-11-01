import LocalAuthentication
import Observation
import SwiftUI
import UIKit

extension Notification.Name {
    static let tripfolioLockNow = Notification.Name("Tripfolio.lockNow")
}

/// Use once around the app's document interface. The separate native window
/// covers presented sheets as well as the root view before app snapshots.
@MainActor
struct PrivacyLockView<Content: View>: View {
    @State private var lock = PrivacyLockController()
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        ZStack {
            if lock.isUnlocked {
                content
            } else {
                PrivacyLockScreen(
                    isActive: lock.isSceneActive,
                    isAuthenticating: lock.isAuthenticating,
                    message: lock.message,
                    unlock: { Task { await lock.authenticate() } }
                )
            }
        }
        .background(PrivacySceneAnchor(lock: lock).frame(width: 0, height: 0))
    }
}

@MainActor
@Observable
private final class PrivacyLockController: NSObject {
    private(set) var isUnlocked = false
    private(set) var isSceneActive = false
    private(set) var isAuthenticating = false
    private(set) var message: String?

    @ObservationIgnored private weak var scene: UIWindowScene?
    @ObservationIgnored private weak var contentWindow: UIWindow?
    @ObservationIgnored private var contentAccessibilityWasHidden = false
    @ObservationIgnored private var shield: UIWindow?
    @ObservationIgnored private var shieldController: UIHostingController<PrivacyLockScreen>?
    @ObservationIgnored private var authenticationContext: LAContext?
    @ObservationIgnored private var authenticationGeneration: UInt64 = 0
    @ObservationIgnored private var isBackgrounded = false
    @ObservationIgnored private var shouldAutomaticallyAuthenticate = true
    @ObservationIgnored private let testingBypass: Bool

    override init() {
        #if DEBUG
        testingBypass = ProcessInfo.processInfo.arguments.contains("--ui-testing-unlocked")
        #else
        testingBypass = false
        #endif
        super.init()
        let center = NotificationCenter.default
        center.addObserver(self, selector: #selector(willDeactivate(_:)), name: UIScene.willDeactivateNotification, object: nil)
        center.addObserver(self, selector: #selector(didActivate(_:)), name: UIScene.didActivateNotification, object: nil)
        center.addObserver(self, selector: #selector(didEnterBackground(_:)), name: UIScene.didEnterBackgroundNotification, object: nil)
        center.addObserver(self, selector: #selector(lockNow), name: .tripfolioLockNow, object: nil)
    }

    func attach(to newWindow: UIWindow?) {
        if contentWindow !== newWindow {
            contentWindow?.accessibilityElementsHidden = contentAccessibilityWasHidden
            contentWindow = newWindow
            contentAccessibilityWasHidden = newWindow?.accessibilityElementsHidden ?? false
        }
        guard let newScene = newWindow?.windowScene else {
            invalidateAuthentication()
            isUnlocked = false
            isSceneActive = false
            isBackgrounded = true
            shouldAutomaticallyAuthenticate = true
            scene = nil
            shield?.isHidden = true
            shield = nil
            shieldController = nil
            return
        }
        guard scene !== newScene else {
            updateShield()
            return
        }
        scene = newScene
        isSceneActive = newScene.activationState == .foregroundActive
        isBackgrounded = newScene.activationState == .background
        let controller = UIHostingController(rootView: screen())
        controller.view.backgroundColor = .systemBackground
        controller.view.accessibilityViewIsModal = true
        let window = UIWindow(windowScene: newScene)
        window.windowLevel = .alert + 1
        window.backgroundColor = .systemBackground
        window.rootViewController = controller
        shield = window
        shieldController = controller
        updateShield()
        if isSceneActive {
            Task { await self.authenticateAutomaticallyIfNeeded() }
        }
    }

    func authenticate() async {
        guard isSceneActive, !isAuthenticating, !isUnlocked else { return }
        shouldAutomaticallyAuthenticate = false
        message = nil
        if testingBypass {
            isUnlocked = true
            updateShield()
            return
        }

        let context = LAContext()
        context.localizedCancelTitle = L10n.service("services.privacy.keepLocked", defaultValue: "Keep Locked")
        context.touchIDAuthenticationAllowableReuseDuration = 0
        var availabilityError: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &availabilityError) else {
            // No passcode means no safe fallback: never reveal document content.
            message = L10n.service("services.privacy.passcodeRequired", defaultValue: "Set a device passcode in Settings to unlock your documents. If authentication is temporarily unavailable, try again.")
            updateShield()
            return
        }

        authenticationGeneration &+= 1
        let generation = authenticationGeneration
        authenticationContext = context
        isAuthenticating = true
        updateShield()
        do {
            // Keep the context on MainActor for invalidation on older SDKs.
            // The framework callback returns only its result across actors.
            let success = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Bool, Error>) in
                context.evaluatePolicy(
                    .deviceOwnerAuthentication,
                    localizedReason: L10n.service("services.privacy.reason", defaultValue: "Unlock your private travel documents.")
                ) { @Sendable success, error in
                    if let error {
                        continuation.resume(throwing: error)
                    } else {
                        continuation.resume(returning: success)
                    }
                }
            }
            guard generation == authenticationGeneration, !isBackgrounded else { return }
            isAuthenticating = false
            authenticationContext = nil
            isUnlocked = success
            if !success { message = L10n.service("services.privacy.incomplete", defaultValue: "Authentication did not complete. Your documents remain locked.") }
        } catch {
            guard generation == authenticationGeneration else { return }
            isAuthenticating = false
            authenticationContext = nil
            isUnlocked = false
            message = L10n.service("services.privacy.retry", defaultValue: "Your documents remain locked. Tap Unlock to try again.")
        }
        updateShield()
    }

    private func authenticateAutomaticallyIfNeeded() async {
        guard shouldAutomaticallyAuthenticate else { return }
        await authenticate()
    }

    @objc private func willDeactivate(_ notification: Notification) {
        guard belongsToScene(notification) else { return }
        isSceneActive = false
        // System permission and authentication prompts temporarily deactivate
        // the scene. Cover immediately without tearing down their presenting
        // views. Actual background entry invalidates access below.
        updateShield()
    }

    @objc private func didActivate(_ notification: Notification) {
        guard belongsToScene(notification) else { return }
        isSceneActive = true
        isBackgrounded = false
        updateShield()
        Task { await self.authenticateAutomaticallyIfNeeded() }
    }

    @objc private func didEnterBackground(_ notification: Notification) {
        guard belongsToScene(notification) else { return }
        isBackgrounded = true
        isSceneActive = false
        invalidateAuthentication()
        isUnlocked = false
        shouldAutomaticallyAuthenticate = true
        updateShield()
    }

    @objc private func lockNow() {
        invalidateAuthentication()
        isUnlocked = false
        message = nil
        shouldAutomaticallyAuthenticate = false
        updateShield()
    }

    private func invalidateAuthentication() {
        // Late success from a prompt that was interrupted by backgrounding must
        // not unlock the next foreground session.
        authenticationGeneration &+= 1
        authenticationContext?.invalidate()
        authenticationContext = nil
        isAuthenticating = false
    }

    private func belongsToScene(_ notification: Notification) -> Bool {
        guard let candidate = notification.object as? UIWindowScene else { return false }
        return candidate === scene
    }

    private func screen() -> PrivacyLockScreen {
        PrivacyLockScreen(
            isActive: isSceneActive,
            isAuthenticating: isAuthenticating,
            message: message,
            unlock: { [weak self] in Task { await self?.authenticate() } }
        )
    }

    private func updateShield() {
        let allowsContent = isSceneActive && isUnlocked
        if !allowsContent {
            // The system keyboard and its predictions are outside the document
            // view covered below. Release input focus before the inactive card
            // is captured; the model still owns every unsaved draft value.
            UIView.performWithoutAnimation {
                contentWindow?.endEditing(true)
            }
        }
        shieldController?.rootView = screen()
        // Native presentations such as Quick Look are siblings of SwiftUI's
        // root. Hide their accessibility tree along with the covered window.
        contentWindow?.accessibilityElementsHidden = allowsContent ? contentAccessibilityWasHidden : true
        // Keep the native cover over all document sheets while locked. It is
        // opaque even before SwiftUI finishes rendering its text and controls.
        shield?.isHidden = allowsContent
    }
}

@MainActor
private struct PrivacySceneAnchor: UIViewRepresentable {
    let lock: PrivacyLockController

    func makeUIView(context: Context) -> SceneAnchorView {
        let view = SceneAnchorView()
        view.didAttach = { [weak lock] window in lock?.attach(to: window) }
        return view
    }

    func updateUIView(_ uiView: SceneAnchorView, context: Context) {}

    static func dismantleUIView(_ uiView: SceneAnchorView, coordinator: ()) {
        uiView.didAttach?(nil)
        uiView.didAttach = nil
    }

    final class SceneAnchorView: UIView {
        var didAttach: ((UIWindow?) -> Void)?

        override func didMoveToWindow() {
            super.didMoveToWindow()
            didAttach?(window)
        }
    }
}

private struct PrivacyLockScreen: View {
    let isActive: Bool
    let isAuthenticating: Bool
    let message: String?
    let unlock: () -> Void

    var body: some View {
        ZStack {
            Color(uiColor: .systemBackground).ignoresSafeArea()
            GeometryReader { geometry in
                ScrollView {
                    VStack(spacing: 20) {
                        Image(systemName: "lock.shield.fill")
                            .font(.system(size: 52, weight: .regular))
                            .foregroundStyle(.tint)
                            .accessibilityHidden(true)
                        Text(L10n.service("services.privacy.title", defaultValue: "TripDocket is locked"))
                            .font(.title2.bold())
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityAddTraits(.isHeader)
                        Text(L10n.service("services.privacy.explanation", defaultValue: "Your travel documents stay private until you unlock."))
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                        if isActive {
                            if let message {
                                Text(message)
                                    .font(.callout)
                                    .multilineTextAlignment(.center)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            if isAuthenticating {
                                ProgressView(L10n.service("services.privacy.authenticating", defaultValue: "Authenticating…"))
                            } else {
                                Button(L10n.service("services.privacy.unlock", defaultValue: "Unlock"), systemImage: "lock.open", action: unlock)
                                    .buttonStyle(.borderedProminent)
                                    .controlSize(.large)
                                    .accessibilityIdentifier("privacy.unlock")
                            }
                        }
                    }
                    .padding(32)
                    .frame(maxWidth: 480)
                    // Keep the existing centered layout when it fits. Larger
                    // text can grow naturally and scroll to the Unlock action.
                    .frame(maxWidth: .infinity, minHeight: geometry.size.height)
                }
                .accessibilityIdentifier("privacy.lock.scroll")
            }
        }
    }
}
