import Foundation
import SwiftUI
import TravelCore
import UniformTypeIdentifiers

/// The model owns prepared bytes and confirmed metadata across privacy teardown.
/// This view never adds an individual document to the library.
struct BatchImportView: View {
    @Environment(AppModel.self) private var model
    @Bindable var draft: BatchImportDraft
    @State private var showsFiles = false
    @State private var pickerError: String?

    private var isCommitting: Bool {
        if case .committing = draft.phase { return true }
        return false
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(L10n.ui("batch.intro", defaultValue: "Choose up to 10 PDF, JPEG or PNG files for this trip, then review every document before saving."))
                    Text(L10n.ui("batch.limits", defaultValue: "Each file can be up to 16 MiB. The entire library can hold up to 64 MiB of originals."))
                    Text(L10n.ui("batch.available", defaultValue: "Available in this library: \(batchSize(model.remainingLibraryBytes))."))
                        .foregroundStyle(.secondary)
                } header: { Text(L10n.ui("batch.title", defaultValue: "Import multiple files")) }

                switch draft.phase {
                case .choosing:
                    Section {
                        Button(L10n.ui("batch.choose", defaultValue: "Choose files"), systemImage: "folder") {
                            pickerError = nil
                            showsFiles = true
                        }
                        .disabled(!model.canUseBatchImport)
                        .accessibilityIdentifier("batch.chooseFiles")
                    }
                case .preparing:
                    Section {
                        ProgressView(
                            L10n.ui("batch.progress", defaultValue: "Preparing files: \(draft.preparedCount) of \(draft.selectedCount)"),
                            value: Double(draft.preparedCount),
                            total: Double(max(1, draft.selectedCount))
                        )
                        Text(L10n.ui("batch.preparingHelp", defaultValue: "Copying the full originals into this unsaved draft. Your library has not changed. Cloud files may need to download first."))
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                case .reviewing, .committing:
                    Section {
                        ForEach(draft.items, id: \.id) { item in
                            NavigationLink {
                                BatchItemReviewView(draft: draft, item: item)
                            } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(item.title.isEmpty ? item.filename : item.title)
                                        .font(.headline)
                                    Text(item.filename).font(.subheadline).foregroundStyle(.secondary)
                                    Text(batchSize(item.byteCount)).font(.caption).foregroundStyle(.secondary)
                                    Label(item.isReviewed ? L10n.ui("batch.reviewed", defaultValue: "Reviewed") : L10n.ui("batch.needsReview", defaultValue: "Needs review"),
                                          systemImage: item.isReviewed ? "checkmark.circle.fill" : "circle")
                                        .font(.subheadline)
                                }
                                .padding(.vertical, 4)
                            }
                            .disabled(isCommitting)
                            .accessibilityLabel(L10n.ui("batch.reviewAX", defaultValue: "Review \(item.title.isEmpty ? item.filename : item.title), file \(item.filename), \(batchSize(item.byteCount)), \(item.isReviewed ? L10n.ui("batch.reviewed", defaultValue: "Reviewed") : L10n.ui("batch.needsReview", defaultValue: "Needs review"))"))
                            .accessibilityIdentifier("batch.review.\(item.id.uuidString)")
                        }
                        if draft.items.isEmpty {
                            Text(L10n.ui("batch.empty", defaultValue: "No files remain in this batch. Cancel to return to the trip and start again."))
                        }
                    } header: {
                        Text(L10n.ui("batch.reviewProgress", defaultValue: "\(draft.items.filter(\.isReviewed).count) of \(draft.items.count) reviewed"))
                    } footer: {
                        Text(L10n.ui("batch.reviewHelp", defaultValue: "Open each file to confirm its title, type, person and expiry-date choice. Editing a confirmed detail makes that file need review again."))
                    }

                    Section {
                        if isCommitting {
                            ProgressView(L10n.ui("batch.saving", defaultValue: "Saving the complete batch…"))
                            Text(L10n.ui("batch.savingHelp", defaultValue: "Please wait until all documents have been saved."))
                                .font(.footnote).foregroundStyle(.secondary)
                        } else {
                            Button {
                                let draftID = draft.id
                                Task { _ = await model.commitBatchImport(draftID: draftID) }
                            } label: {
                                Text(L10n.ui("batch.saveCount", defaultValue: "Save \(draft.items.count) documents"))
                            }
                            .disabled(!draft.canSave || !model.canUseBatchImport || draft.items.isEmpty)
                            .accessibilityIdentifier("batch.save")
                            Text(L10n.ui("batch.atomicHelp", defaultValue: "The whole batch is added together. If saving fails, none of these documents is added."))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }

                if !model.canUseBatchImport {
                    Section {
                        Text(L10n.ui("batch.proHelp", defaultValue: "Pro is required to prepare and save multiple files. A prepared draft can be reviewed, but cannot be saved while Pro is inactive. Existing documents stay available in your library."))
                            .foregroundStyle(.secondary)
                    }
                }
                if let message = draft.errorMessage ?? pickerError {
                    Section {
                        Label(message, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                            .accessibilityIdentifier("batch.error")
                    }
                }
                Section {
                    Text(L10n.ui("batch.memoryHelp", defaultValue: "Unsaved files and details stay in memory while the app is running, including while it is locked. Quitting the app discards this draft."))
                    Text(L10n.ui("batch.cancelHelp", defaultValue: "Cancel discards the prepared copies. The files you selected and your current library are left unchanged."))
                } header: { Text(L10n.ui("batch.beforeSave", defaultValue: "Before you save")) }
                    .font(.footnote).foregroundStyle(.secondary)
            }
            .navigationTitle(L10n.ui("batch.navigationTitle", defaultValue: "Import files"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.ui("common.cancel", defaultValue: "Cancel")) { [draftID = draft.id] in
                        model.cancelBatchImport(draftID: draftID)
                    }
                        .disabled(isCommitting)
                        .accessibilityIdentifier("batch.cancel")
                }
            }
            .interactiveDismissDisabled(true)
            .fileImporter(isPresented: $showsFiles, allowedContentTypes: [.pdf, .jpeg, .png],
                          allowsMultipleSelection: true) { [draftID = draft.id] result in
                guard model.batchImportDraft?.id == draftID else { return }
                switch result {
                case .success(let urls):
                    guard !urls.isEmpty else { return }
                    guard urls.count <= 10 else {
                        pickerError = L10n.ui("batch.tooMany", defaultValue: "Choose no more than 10 files. No files were prepared or added.")
                        return
                    }
                    pickerError = nil
                    model.prepareBatchImport(urls: urls, draftID: draftID)
                case .failure(let error):
                    let failure = error as NSError
                    if failure.domain != NSCocoaErrorDomain || failure.code != CocoaError.userCancelled.rawValue {
                        pickerError = error.localizedDescription
                    }
                }
            }
        }
    }
}

private struct BatchItemReviewView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @Bindable var draft: BatchImportDraft
    @Bindable var item: BatchImportItem
    @State private var preview: BatchPreviewFile?
    @State private var previewCleanupURL: URL?
    @State private var previewError: String?

    private var isCommitting: Bool {
        if case .committing = draft.phase { return true }
        return false
    }

    var body: some View {
        Form {
            Section(L10n.ui("original.file", defaultValue: "Original file")) {
                Text(item.filename).textSelection(.enabled)
                Text(batchSize(item.byteCount)).foregroundStyle(.secondary)
                Button(L10n.ui("batch.viewOriginal", defaultValue: "View original"), systemImage: "doc.text.magnifyingglass") {
                    if let url = model.batchPreviewURL(itemID: item.id) {
                        previewError = nil
                        previewCleanupURL = url
                        preview = BatchPreviewFile(url: url)
                    } else {
                        previewError = L10n.ui("batch.previewError", defaultValue: "The prepared original could not be opened. Try again or remove this file from the batch.")
                    }
                }
                .accessibilityIdentifier("batch.viewOriginal")
                if let previewError {
                    Label(previewError, systemImage: "exclamationmark.triangle").foregroundStyle(.red)
                }
            }
            Section(L10n.ui("document.details", defaultValue: "Document details")) {
                TextField(L10n.ui("document.title", defaultValue: "Document title"), text: $item.title, axis: .vertical)
                    .accessibilityIdentifier("batch.title")
                Picker(L10n.ui("document.type", defaultValue: "Type"), selection: $item.kind) {
                    ForEach(DocumentKind.allCases, id: \.self) { kind in
                        Text(kind.displayName).tag(kind)
                    }
                }
                .pickerStyle(.navigationLink)
                Picker(L10n.ui("document.person", defaultValue: "Person"), selection: $item.travelerID) {
                    Text(L10n.ui("document.unassigned", defaultValue: "Everyone / unassigned")).tag(Optional<UUID>.none)
                    ForEach(model.library.travelers, id: \.id) { person in
                        Text(person.name).tag(Optional(person.id))
                    }
                }
                .pickerStyle(.navigationLink)
                Toggle(L10n.ui("document.addExpiry", defaultValue: "Add confirmed expiry date"), isOn: $item.hasExpiry)
                if item.hasExpiry {
                    DatePicker(L10n.ui("document.expiry", defaultValue: "Expiry date"), selection: $item.expiryDate, displayedComponents: .date)
                    Text(L10n.ui("batch.dateHelp", defaultValue: "Read the date from the original. The app does not infer a date or check travel requirements."))
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    Text(L10n.ui("batch.noExpiry", defaultValue: "No expiry date will be saved for this document."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            Section {
                Text(L10n.ui("batch.confirmHelp", defaultValue: "Confirm that these details belong to this file. “Everyone / unassigned” and no expiry date are valid choices."))
                Button(L10n.ui("batch.confirm", defaultValue: "Confirm this document"), systemImage: "checkmark.circle") {
                    model.confirmBatchItem(id: item.id)
                    if item.isReviewed { dismiss() }
                }
                .disabled(item.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityIdentifier("batch.confirmItem")
                if item.isReviewed {
                    Label(L10n.ui("batch.confirmed", defaultValue: "These details are confirmed"), systemImage: "checkmark.circle.fill")
                }
                if let error = draft.errorMessage {
                    Label(error, systemImage: "exclamationmark.triangle").foregroundStyle(.red)
                }
            } header: { Text(L10n.ui("batch.reviewRequired", defaultValue: "Review required")) }
            Section {
                Button(L10n.ui("batch.remove", defaultValue: "Remove from batch"), role: .destructive) {
                    model.removeBatchItem(id: item.id)
                    dismiss()
                }
                .accessibilityIdentifier("batch.removeItem")
                Text(L10n.ui("batch.removeHelp", defaultValue: "This only removes the unsaved copy from this batch. The original file is kept."))
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .disabled(isCommitting)
        .navigationTitle(L10n.ui("batch.reviewTitle", defaultValue: "Review document"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $preview, onDismiss: {
            // Match original-preview cleanup: background teardown may interrupt
            // a system share extension, which must retain access to its copy.
            if scenePhase == .active, let url = previewCleanupURL { model.removeTemporary(url) }
            previewCleanupURL = nil
        }) { file in
            PreviewSheet(url: file.url)
        }
    }
}

private struct BatchPreviewFile: Identifiable {
    let id = UUID()
    let url: URL
}

private func batchSize(_ bytes: Int) -> String {
    L10n.byteCount(Int64(max(0, bytes)), style: .binary)
}
