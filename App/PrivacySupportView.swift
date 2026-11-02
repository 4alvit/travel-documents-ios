import SwiftUI

/// Bundled guidance is independent of the library and purchase state.
/// Only the explicit confirmation button hands a fixed public URL to the system.
struct PrivacySupportView: View {
    @Environment(\.openURL) private var openURL
    @State private var selectedLink: PrivacySupportLink?
    #if DEBUG && targetEnvironment(simulator)
    @Environment(\.scenePhase) private var scenePhase
    @State private var diagnostics = GuidanceDiagnostics()
    #endif

    var body: some View {
        List {
            Text(L10n.ui("privacySupport.offline", defaultValue: "This page is available offline and without Pro. Website links need an internet connection."))
                .accessibilityIdentifier("privacySupport.offline")
            Section(L10n.ui("privacySupport.local.title", defaultValue: "On this device")) {
                Text(L10n.ui("privacySupport.local.body", defaultValue: "Your imported originals and trip details are stored on this device. Text recognition (OCR) runs here too. TripDocket has no developer-operated document server and does not send your library to the developer. No TripDocket account is needed. The app includes no advertising, analytics or crash-upload SDK."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.local.body")
            }
            Section(L10n.ui("privacySupport.access.title", defaultValue: "Unlocking & protection")) {
                Text(L10n.ui("privacySupport.access.body", defaultValue: "A device passcode is required. TripDocket uses Apple’s Face ID, Touch ID or passcode prompt to unlock, and system file protection for saved library files. The app covers its content when inactive."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.access.body")
            }
            Section(L10n.ui("privacySupport.deletion.title", defaultValue: "Deleting data")) {
                Text(L10n.ui("privacySupport.deletion.body", defaultValue: "Deleting a document removes it from the active library. Deleting a trip also removes its documents. Copies already exported or kept in device backups are managed separately; the app cannot erase them. Deleting a person keeps their documents and removes the assignment."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.deletion.body")
                Text(L10n.ui("privacySupport.deletion.temporary", defaultValue: "Previews and exports use protected temporary copies. Cleanup may happen after the operation or on a later launch. Unsaved batch imports stay in memory and are lost if the app quits."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.deletion.temporary")
            }
            Section(L10n.ui("privacySupport.export.title", defaultValue: "Export & recovery")) {
                Text(L10n.ui("privacySupport.export.body", defaultValue: "Exported files and .tripbackup copies are not encrypted by TripDocket. A recipient or app with access to the destination can read them. Choose where you save or send them carefully."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.export.body")
                Text(L10n.ui("privacySupport.export.restore", defaultValue: "Restoring a backup replaces the current library. Save a backup first if you need to keep it. Losing the device and all backups can mean losing your documents. After a restore, schedule reminders again. Viewing, editing, deletion, export and recovery of existing data do not require Pro."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.export.restore")
            }
            Section(L10n.ui("privacySupport.apple.title", defaultValue: "Apple services")) {
                Text(L10n.ui("privacySupport.apple.purchases", defaultValue: "Purchases use Apple’s StoreKit. TripDocket reads product information and verified Pro access, not payment-card details. Restore Purchases may ask you to sign in to your Apple Account; it restores Pro access, not documents."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.apple.purchases")
                Text(L10n.ui("privacySupport.apple.backup", defaultValue: "Depending on your Apple settings, device backups may include the library. TripDocket has no automatic library sync between devices."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.apple.backup")
            }
            Section(L10n.ui("privacySupport.limits.title", defaultValue: "File limits")) {
                Text(L10n.ui("privacySupport.limits.body", defaultValue: "Up to 16 MiB per original and 64 MiB of originals in the library. A backup opened for restore must be no larger than 96 MiB. Pro batch import accepts up to 10 files at once. Dates are confirmed by you. Reminders do not check entry requirements or whether documents are valid for a destination."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.limits.body")
            }
            Section(L10n.ui("privacySupport.help.title", defaultValue: "Before asking for help")) {
                Text(L10n.ui("privacySupport.help.body", defaultValue: "For a file stored in the cloud, finish downloading it in Files before importing. Keep a backup before troubleshooting; do not delete the app while it holds your only copy."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.help.body")
            }
            Section(L10n.ui("privacySupport.support.title", defaultValue: "Public support")) {
                Text(L10n.ui("privacySupport.support.body", defaultValue: "Report app problems in the project’s public GitHub Issues. Anyone can read these reports. Include the app version, device, OS version and steps using fictional data."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.support.body")
                Text(L10n.ui("privacySupport.support.warning", defaultValue: "Do not post documents, purchase receipts, credentials or personal backups. Check screenshots for private information before posting."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.support.warning")
                websiteButton(.supportIssue)
            }
            Section(L10n.ui("privacySupport.web.title", defaultValue: "Online documents")) {
                Text(L10n.ui("privacySupport.web.preview", defaultValue: "The linked privacy and support documents are published previews. They are not final App Store policies."))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.web.preview")
                websiteButton(.privacyPreview)
                websiteButton(.supportPreview)
            }
            Section(L10n.ui("privacySupport.developer.title", defaultValue: "Developer")) {
                Text(L10n.ui("privacySupport.developer.name", defaultValue: "alvit (4alvit)"))
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityIdentifier("privacySupport.developer.name")
                websiteButton(.developer)
            }
        }
        .accessibilityIdentifier("privacySupport.content")
        #if DEBUG && targetEnvironment(simulator)
        .modifier(GuidanceDiagnosticValue(value: diagnostics.value(selection: selectedLink, scene: scenePhase)))
        #endif
        .navigationTitle(L10n.ui("privacySupport.title", defaultValue: "Privacy & support"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selectedLink, onDismiss: {
            #if DEBUG && targetEnvironment(simulator)
            diagnostics.didDismiss()
            #endif
        }) { link in
            NavigationStack {
                List {
                    Text(L10n.ui("privacySupport.external.body", defaultValue: "This opens GitHub outside TripDocket and needs an internet connection. GitHub handles the web visit under its own policies. TripDocket does not attach your documents to this link."))
                        .fixedSize(horizontal: false, vertical: true)
                    if link == .supportIssue {
                        Text(L10n.ui("privacySupport.support.warning", defaultValue: "Do not post documents, purchase receipts, credentials or personal backups. Check screenshots for private information before posting."))
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("privacySupport.external.warning")
                    }
                    Text(link.url().absoluteString)
                        .font(.footnote)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier("privacySupport.external.destination")
                    Button(L10n.ui("privacySupport.external.open", defaultValue: "Open website")) {
                        selectedLink = nil
                        openURL(link.url())
                    }
                    .accessibilityIdentifier("privacySupport.external.open")
                }
                .navigationTitle(L10n.ui("privacySupport.external.title", defaultValue: "Open a website?"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(L10n.ui("common.cancel", defaultValue: "Cancel")) {
                            #if DEBUG && targetEnvironment(simulator)
                            diagnostics.receivedCancel(link)
                            #endif
                            selectedLink = nil
                            #if DEBUG && targetEnvironment(simulator)
                            diagnostics.recordSelectionAfterCancel(selectedLink)
                            #endif
                        }
                        .accessibilityIdentifier("privacySupport.external.cancel")
                        #if DEBUG && targetEnvironment(simulator)
                        .modifier(GuidanceDiagnosticValue(value: diagnostics.value(selection: selectedLink, scene: scenePhase)))
                        #endif
                    }
                }
            }
        }
    }

    private func websiteButton(_ link: PrivacySupportLink) -> some View {
        Button {
            selectedLink = link
            #if DEBUG && targetEnvironment(simulator)
            diagnostics.didPresent(link)
            #endif
        } label: {
            Label(link.title, systemImage: "arrow.up.right.square")
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityIdentifier("privacySupport.link.\(link.rawValue)")
    }
}

#if DEBUG && targetEnvironment(simulator)
/// Opt-in observations only. Values contain fixed link kinds and counters, never
/// document data, destinations, error payloads or a replacement acceptance result.
private struct GuidanceDiagnostics {
    private let enabled = ProcessInfo.processInfo.arguments.contains("--ui-testing-guidance-diagnostics")
    private var presentations = 0
    private var cancellations = 0
    private var dismissals = 0
    private var lastPresented: PrivacySupportLink?
    private var lastCancelled: PrivacySupportLink?
    private var selectionAfterCancel = "notObserved"

    mutating func didPresent(_ link: PrivacySupportLink) {
        guard enabled else { return }
        presentations += 1
        lastPresented = link
    }

    mutating func receivedCancel(_ link: PrivacySupportLink) {
        guard enabled else { return }
        cancellations += 1
        lastCancelled = link
    }

    mutating func recordSelectionAfterCancel(_ selection: PrivacySupportLink?) {
        guard enabled else { return }
        selectionAfterCancel = selection?.rawValue ?? "none"
    }

    mutating func didDismiss() {
        guard enabled else { return }
        dismissals += 1
    }

    func value(selection: PrivacySupportLink?, scene: ScenePhase) -> String? {
        guard enabled else { return nil }
        let phase: String
        switch scene {
        case .active: phase = "active"
        case .inactive: phase = "inactive"
        case .background: phase = "background"
        @unknown default: phase = "unknown"
        }
        return "guidance-diagnostic presentations=\(presentations) lastPresented=\(lastPresented?.rawValue ?? "none") cancellations=\(cancellations) lastCancelled=\(lastCancelled?.rawValue ?? "none") selectionAfterCancel=\(selectionAfterCancel) selection=\(selection?.rawValue ?? "none") dismissals=\(dismissals) scene=\(phase)"
    }
}

private struct GuidanceDiagnosticValue: ViewModifier {
    let value: String?

    @ViewBuilder
    func body(content: Content) -> some View {
        if let value {
            content.accessibilityValue(value)
        } else {
            content
        }
    }
}
#endif

/// Fixed, public destinations only. Preview documents stay pinned to an audited
/// published commit until stable production policies are approved and published.
enum PrivacySupportLink: String, CaseIterable, Identifiable {
    case supportIssue, privacyPreview, supportPreview, developer
    var id: Self { self }

    var title: String {
        switch self {
        case .supportIssue: L10n.ui("privacySupport.support.open", defaultValue: "Open public support")
        case .privacyPreview: L10n.ui("privacySupport.web.privacy", defaultValue: "Privacy preview (web)")
        case .supportPreview: L10n.ui("privacySupport.web.support", defaultValue: "Support preview (web)")
        case .developer: L10n.ui("privacySupport.developer.open", defaultValue: "Developer on GitHub")
        }
    }

    func url(preferredLanguages: [String] = Bundle.main.preferredLocalizations) -> URL {
        let language = L10n.language(preferences: preferredLanguages)
        let root = URL(string: "https://github.com/4alvit")!
        let repo = root.appendingPathComponent("travel-documents-ios")
        let documents = repo.appendingPathComponent("blob/1391b30776cd6ea48eab97cd92d4b098ff8f9474/docs/app-store/drafts")
        switch self {
        case .supportIssue: return repo.appendingPathComponent("issues")
        case .developer: return root
        case .privacyPreview:
            return documents.appendingPathComponent(language == "ru" ? "privacy-ru.md" : "privacy-en-US.md")
        case .supportPreview:
            return documents.appendingPathComponent(language == "ru" ? "support-ru.md" : "support-en-US.md")
        }
    }
}
