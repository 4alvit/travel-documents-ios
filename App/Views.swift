import SwiftUI
import TravelCore
import UniformTypeIdentifiers

private enum TripStyle {
    static let accent = Color(red: 0.05, green: 0.43, blue: 0.42)
    static let tint = Color(red: 0.86, green: 0.94, blue: 0.92)
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TabView {
            TripsView()
                .tabItem { Label(L10n.ui("nav.trips", defaultValue: "Trips"), systemImage: "suitcase.rolling") }
            TravelersView()
                .tabItem { Label(L10n.ui("nav.people", defaultValue: "People"), systemImage: "person.2") }
            SettingsView()
                .tabItem { Label(L10n.ui("nav.settings", defaultValue: "Settings"), systemImage: "gearshape") }
        }
        .tint(TripStyle.accent)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if model.isBusy {
                HStack(spacing: 10) {
                    ProgressView()
                    Text(L10n.ui("library.working", defaultValue: "Working with your local library…")).font(.footnote)
                }
                .frame(maxWidth: .infinity).padding(10).background(.regularMaterial)
                .accessibilityElement(children: .combine)
            }
        }
        .alert(L10n.ui("common.actionFailed", defaultValue: "Couldn’t complete action"), isPresented: Binding(
            get: { model.errorMessage != nil },
            set: { if !$0 { model.errorMessage = nil } }
        )) {
            Button(L10n.ui("common.ok", defaultValue: "OK"), role: .cancel) { model.errorMessage = nil }
        } message: {
            Text(model.errorMessage ?? L10n.ui("common.tryAgain", defaultValue: "Please try again."))
        }
        .sheet(item: Binding(
            get: { model.documentEditDraft },
            set: { _ in
                // Privacy removes this view while locked. Only explicit Cancel
                // or a successful Save may discard the model's in-memory draft.
            }
        )) { draft in
            EditDocumentView(draft: draft)
        }
        .sheet(item: Binding(
            get: { model.batchImportDraft },
            set: { _ in
                // A privacy lock removes this view. The model discards this RAM
                // draft on cancellation, saved import or source-library change.
            }
        )) { draft in
            BatchImportView(draft: draft)
        }
    }
}

private struct TripsView: View {
    @Environment(AppModel.self) private var model
    @State private var showsNewTrip = false
    @State private var showsPro = false
    @State private var editingTrip: Trip?
    @State private var deletingTrip: Trip?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        Label(L10n.ui("trips.eyebrow", defaultValue: "YOUR OFFLINE TRAVEL FOLDER"), systemImage: "lock.shield")
                            .font(.caption.weight(.semibold)).foregroundStyle(TripStyle.accent)
                        Text(L10n.ui("trips.hero", defaultValue: "Ready when\nyou leave."))
                            .font(.system(.largeTitle, design: .rounded, weight: .bold))
                            .fixedSize(horizontal: false, vertical: true)
                        Text(L10n.ui("trips.heroBody", defaultValue: "Keep the originals together. Check every file before your trip."))
                            .foregroundStyle(.secondary)
                    }.padding(.vertical, 8)
                }.listRowBackground(TripStyle.tint.opacity(0.45))

                if model.library.trips.isEmpty {
                    Section {
                        ContentUnavailableView {
                            Label(L10n.ui("trips.emptyTitle", defaultValue: "Your first trip starts here"), systemImage: "suitcase.rolling")
                        } description: {
                            Text(L10n.ui("trips.emptyBody", defaultValue: "Create a trip, add travel documents, then verify the complete files are available on this device."))
                        } actions: {
                            Button(L10n.ui("trips.createEmpty", defaultValue: "Create a trip"), action: addTrip).buttonStyle(.borderedProminent)
                        }
                    }
                } else {
                    Section(L10n.ui("trips.section", defaultValue: "Your trips")) {
                        ForEach(model.library.trips, id: \.id) { trip in
                            NavigationLink {
                                TripDetailView(tripID: trip.id)
                            } label: {
                                TripRow(trip: trip, documentCount: model.library.documents.filter { $0.tripID == trip.id }.count)
                            }
                            .contextMenu {
                                Button(L10n.ui("trip.edit", defaultValue: "Edit trip"), systemImage: "pencil") { editingTrip = trip }
                                Button(L10n.ui("trip.delete", defaultValue: "Delete trip"), systemImage: "trash", role: .destructive) { deletingTrip = trip }
                            }
                            .swipeActions(edge: .leading) {
                                Button(L10n.ui("common.edit", defaultValue: "Edit"), systemImage: "pencil") { editingTrip = trip }.tint(TripStyle.accent)
                            }
                            .swipeActions {
                                Button(L10n.ui("common.delete", defaultValue: "Delete"), role: .destructive) { deletingTrip = trip }
                            }
                            .accessibilityAction(named: L10n.ui("trip.edit", defaultValue: "Edit trip")) { editingTrip = trip }
                            .accessibilityAction(named: L10n.ui("trip.delete", defaultValue: "Delete trip")) { deletingTrip = trip }
                        }
                    }
                }
                Section {
                    Label(L10n.ui("trips.localNotice", defaultValue: "Documents stay in your local library. Export a backup before changing devices."), systemImage: "internaldrive")
                        .font(.footnote).foregroundStyle(.secondary)
                    if !model.purchases.isPro {
                        Button { showsPro = true } label: {
                            HStack {
                                Label(L10n.ui("trips.freeLimit", defaultValue: "Free: 1 trip · 2 people · 8 documents"), systemImage: "sparkles")
                                    .font(.footnote)
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption)
                            }
                        }
                    }
                }
                NoticeRow()
            }
            .navigationTitle(L10n.ui("brand.name", defaultValue: "TripDocket"))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: addTrip) { Label(L10n.ui("trip.create", defaultValue: "Create trip"), systemImage: "plus") }
                        .disabled(model.isBusy)
                }
            }
            .sheet(isPresented: $showsNewTrip) { NewTripView() }
            .sheet(isPresented: $showsPro) { ProView() }
            .sheet(item: $editingTrip) { trip in NewTripView(trip: trip) }
            .modifier(TripDeletionConfirmation(pendingTrip: $deletingTrip))
        }
    }

    private func addTrip() {
        if model.canAddTrip { showsNewTrip = true } else { showsPro = true }
    }
}

private struct TripRow: View {
    let trip: Trip
    let documentCount: Int
    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "suitcase.rolling.fill")
                .font(.title2).foregroundStyle(TripStyle.accent)
                .frame(width: 44, height: 48).background(TripStyle.tint, in: RoundedRectangle(cornerRadius: 12))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text(trip.title).font(.headline)
                if let departure = trip.departureDate {
                    Text(TravelDate.local(from: departure), format: .dateTime.month(.wide).day().year())
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Text(L10n.ui("count.documents", defaultValue: "\(documentCount) documents"))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.padding(.vertical, 8)
    }
}

private struct NewTripView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var hasDate = false
    @State private var departure = Date()
    private let trip: Trip?

    init(trip: Trip? = nil) {
        self.trip = trip
        _title = State(initialValue: trip?.title ?? "")
        _hasDate = State(initialValue: trip?.departureDate != nil)
        _departure = State(initialValue: trip?.departureDate.map { TravelDate.local(from: $0) } ?? Date())
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(L10n.ui("trip.details", defaultValue: "Trip details")) {
                    TextField(L10n.ui("trip.name", defaultValue: "Trip name"), text: $title).textInputAutocapitalization(.words)
                        .accessibilityLabel(L10n.ui("trip.name", defaultValue: "Trip name"))
                    Toggle(L10n.ui("trip.addDate", defaultValue: "Add departure date"), isOn: $hasDate)
                    if hasDate { DatePicker(L10n.ui("trip.departure", defaultValue: "Departure"), selection: $departure, displayedComponents: .date) }
                }
                Section {
                    Text(trip == nil ? L10n.ui("trip.newHelp", defaultValue: "Start with one trip. You can add documents for everyone traveling together.") : L10n.ui("trip.editHelp", defaultValue: "Changing the trip details keeps its original documents and people."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                InlineErrorRow()
            }
            .navigationTitle(trip == nil ? L10n.ui("trip.new", defaultValue: "New trip") : L10n.ui("trip.edit", defaultValue: "Edit trip")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(L10n.ui("common.cancel", defaultValue: "Cancel")) { dismiss() }.disabled(model.isBusy) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(trip == nil ? L10n.ui("common.create", defaultValue: "Create") : L10n.ui("common.save", defaultValue: "Save")) {
                        Task {
                            let value = title.trimmingCharacters(in: .whitespacesAndNewlines)
                            if let trip {
                                model.errorMessage = nil
                                await model.updateTrip(id: trip.id, title: value, departureDate: hasDate ? departure : nil)
                                if model.errorMessage == nil,
                                   let saved = model.library.trips.first(where: { $0.id == trip.id }),
                                   saved.title == value, saved.departureDate == (hasDate ? TravelDate.stored(from: departure) : nil) { dismiss() }
                            } else {
                                let count = model.library.trips.count
                                await model.createTrip(title: value, departureDate: hasDate ? departure : nil)
                                if model.library.trips.count > count { dismiss() }
                            }
                        }
                    }.disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isBusy)
                }
            }.interactiveDismissDisabled(model.isBusy)
        }
    }
}

private struct TripDetailView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    let tripID: UUID
    @State private var showsImport = false
    @State private var showsPro = false
    @State private var selecting = false
    @State private var selectedIDs: Set<UUID> = []
    @State private var asksExport = false
    @State private var preview: PresentedFile?
    @State private var share: PresentedFile?
    @State private var previewCleanupURL: URL?
    @State private var pendingDelete: TravelDocument?
    @State private var pendingReminder: TravelDocument?
    @State private var actionMessage: String?
    @State private var searchText = ""
    @State private var editingTrip: Trip?
    @State private var deletingTrip: Trip?

    private var trip: Trip? { model.library.trips.first { $0.id == tripID } }
    private var documents: [TravelDocument] { model.library.documents.filter { $0.tripID == tripID } }
    private var filteredDocuments: [TravelDocument] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return documents }
        return documents.filter { document in
            let person = model.library.travelers.first { $0.id == document.travelerID }?.name ?? ""
            return [document.title, document.originalFilename, document.kind.displayName, person]
                .contains { $0.localizedCaseInsensitiveContains(query) }
        }
    }
    private var exportIDs: Set<UUID> { selecting ? selectedIDs : Set(documents.map(\.id)) }

    var body: some View {
        List {
            if let trip {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Label(L10n.ui("readiness.eyebrow", defaultValue: "BEFORE YOU GO"), systemImage: "checkmark.shield")
                            .font(.caption.weight(.semibold)).foregroundStyle(TripStyle.accent)
                        if let departure = trip.departureDate {
                            Text(TravelDate.local(from: departure), format: .dateTime.weekday(.wide).month(.wide).day())
                                .font(.title3.weight(.semibold))
                        }
                        Text(L10n.ui("readiness.intro", defaultValue: "Verify the complete original files, then try opening them in Airplane Mode."))
                            .font(.subheadline).foregroundStyle(.secondary)
                        Button {
                            Task { await model.checkReadiness(tripID: tripID) }
                        } label: {
                            Label(documents.count == 1 ? L10n.ui("readiness.checkOne", defaultValue: "Check original") : L10n.ui("readiness.checkAll", defaultValue: "Check all \(documents.count) originals"), systemImage: "checkmark.circle")
                                .frame(maxWidth: .infinity)
                        }.buttonStyle(.borderedProminent).disabled(documents.isEmpty || model.isBusy)
                        readinessSummary
                    }.padding(.vertical, 8)
                }.listRowBackground(TripStyle.tint.opacity(0.35))
            }
            if documents.isEmpty {
                Section {
                    ContentUnavailableView {
                        Label(L10n.ui("documents.emptyTitle", defaultValue: "Your documents, together"), systemImage: "doc.on.doc")
                    } description: {
                        Text(L10n.ui("documents.emptyBody", defaultValue: "Import a PDF, JPEG or PNG, or scan a paper document. Add passports, insurance, tickets and bookings."))
                    } actions: {
                        Button(L10n.ui("document.add", defaultValue: "Add document"), action: addDocument).buttonStyle(.borderedProminent)
                    }
                }
            } else {
                Section {
                    ForEach(filteredDocuments, id: \.id) { document in
                        Button {
                            if selecting { toggleSelection(document.id) }
                            else { open(document) }
                        } label: {
                            DocumentRow(document: document,
                                traveler: model.library.travelers.first { $0.id == document.travelerID }?.name,
                                readiness: model.readiness[document.id],
                                selection: selecting ? selectedIDs.contains(document.id) : nil)
                        }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button(L10n.ui("document.open", defaultValue: "Open original"), systemImage: "doc.text.magnifyingglass") { open(document) }
                            Button(L10n.ui("document.editDetails", defaultValue: "Edit details"), systemImage: "pencil") { model.beginEditingDocument(document) }
                            if document.expiryDate != nil {
                                Button(L10n.ui("document.reminder", defaultValue: "Set expiry reminder"), systemImage: "bell") {
                                    if model.purchases.isPro { pendingReminder = document }
                                    else { showsPro = true }
                                }
                            }
                            Button(L10n.ui("document.delete", defaultValue: "Delete document"), systemImage: "trash", role: .destructive) { pendingDelete = document }
                        }
                        .swipeActions {
                            Button(L10n.ui("common.delete", defaultValue: "Delete"), role: .destructive) { pendingDelete = document }
                        }
                        .swipeActions(edge: .leading) {
                            Button(L10n.ui("common.edit", defaultValue: "Edit"), systemImage: "pencil") { model.beginEditingDocument(document) }.tint(TripStyle.accent)
                        }
                        .accessibilityAction(named: L10n.ui("document.editAX", defaultValue: "Edit document details")) { model.beginEditingDocument(document) }
                        .accessibilityHint(selecting ? L10n.ui("document.selectAX", defaultValue: "Double tap to change selection") : L10n.ui("document.openAX", defaultValue: "Opens the full original. More actions are available."))
                    }
                    if filteredDocuments.isEmpty {
                        ContentUnavailableView.search(text: searchText)
                    }
                } header: {
                    HStack {
                        Text(selecting ? L10n.ui("selection.count", defaultValue: "\(selectedIDs.count) selected") : L10n.ui("documents.title", defaultValue: "Documents"))
                        Spacer()
                        if selecting {
                            Button(selectedIDs.count == documents.count ? L10n.ui("selection.none", defaultValue: "Deselect all") : L10n.ui("selection.all", defaultValue: "Select all")) {
                                selectedIDs = selectedIDs.count == documents.count ? [] : Set(documents.map(\.id))
                            }
                        }
                    }
                } footer: {
                    Text(L10n.ui("readiness.help", defaultValue: "A check reads and verifies the entire original. “Not checked” and a preview are not proof that a file is available offline."))
                }
                Section {
                    Button { asksExport = true } label: {
                        Label(selecting ? L10n.ui("packet.exportSelected", defaultValue: "Export selected packet") : L10n.ui("packet.exportTrip", defaultValue: "Export trip packet"), systemImage: "square.and.arrow.up")
                    }.disabled(exportIDs.isEmpty || model.isBusy)
                    if selecting {
                        Button(L10n.ui("selection.finish", defaultValue: "Finish selecting")) { selecting = false; selectedIDs = [] }
                    } else {
                        Button(L10n.ui("selection.start", defaultValue: "Select specific documents"), systemImage: "checkmark.circle") { selecting = true }
                    }
                } footer: {
                    Text(L10n.ui("packet.help", defaultValue: "Packets can be restored in TripDocket on another device. Restoring replaces that device’s TripDocket library."))
                }
            }
            NoticeRow()
        }
        .navigationTitle(trip?.title ?? L10n.ui("trip.fallback", defaultValue: "Trip"))
        .searchable(text: $searchText, prompt: L10n.ui("search.prompt", defaultValue: "Title, person or document type"))
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button(L10n.ui("batch.proAction", defaultValue: "Import multiple files · Pro"), systemImage: "doc.on.doc") {
                        if model.canUseBatchImport { model.beginBatchImport(tripID: tripID) }
                        else { showsPro = true }
                    }
                    Button(L10n.ui("trip.edit", defaultValue: "Edit trip"), systemImage: "pencil") { editingTrip = trip }
                    Button(L10n.ui("trip.delete", defaultValue: "Delete trip"), systemImage: "trash", role: .destructive) { deletingTrip = trip }
                } label: { Label(L10n.ui("trip.actions", defaultValue: "Trip actions"), systemImage: "ellipsis.circle") }
                    .disabled(model.isBusy)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button(action: addDocument) { Label(L10n.ui("document.add", defaultValue: "Add document"), systemImage: "plus") }
                    .disabled(model.isBusy)
            }
        }
        .sheet(isPresented: $showsImport) { ImportDocumentView(tripID: tripID) }
        .sheet(isPresented: $showsPro) { ProView() }
        .sheet(item: $editingTrip) { trip in NewTripView(trip: trip) }
        .modifier(TripDeletionConfirmation(pendingTrip: $deletingTrip, didDelete: { dismiss() }))
        .sheet(item: $preview, onDismiss: {
            // QuickLook's own share extension may still read this URL after
            // backgrounding. Interrupted previews are pruned on next use/launch.
            if scenePhase == .active, let url = previewCleanupURL { model.removeTemporary(url) }
            previewCleanupURL = nil
        }) { file in PreviewSheet(url: file.url) }
        .sheet(item: $share) { file in
            ExplicitShareSheet(url: file.url) { model.removeTemporary(file.url) }
        }
        .confirmationDialog(L10n.ui("packet.warning.title", defaultValue: "Export an unencrypted packet?"), isPresented: $asksExport, titleVisibility: .visible) {
            Button(L10n.ui("common.export", defaultValue: "Export…")) {
                let ids = exportIDs
                Task {
                    if let url = await model.makeBackup(documentIDs: ids) {
                        share = PresentedFile(url: url)
                    }
                }
            }
            Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) {}
        } message: {
            Text(L10n.ui("packet.warning.body", defaultValue: "The packet contains \(exportIDs.count) original files and their details in readable, unencrypted form. Choose a trusted destination or recipient. Copies you send cannot be revoked."))
        }
        .confirmationDialog(L10n.ui("document.deleteTitle", defaultValue: "Delete this original?"), isPresented: Binding(
            get: { pendingDelete != nil }, set: { if !$0 { pendingDelete = nil } }
        ), titleVisibility: .visible) {
            Button(L10n.ui("document.delete", defaultValue: "Delete document"), role: .destructive) {
                if let document = pendingDelete {
                    selectedIDs.remove(document.id)
                    Task { await model.deleteDocument(id: document.id) }
                }
                pendingDelete = nil
            }
            Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { pendingDelete = nil }
        } message: {
            Text(L10n.ui("document.deleteBody", defaultValue: "“\(pendingDelete?.title ?? L10n.ui("document.fallback", defaultValue: "Document"))” will be removed from this device’s library. Previously exported copies are unchanged."))
        }
        .confirmationDialog(L10n.ui("reminder.confirmTitle", defaultValue: "Set an expiry reminder?"), isPresented: Binding(
            get: { pendingReminder != nil }, set: { if !$0 { pendingReminder = nil } }
        ), titleVisibility: .visible) {
            Button(L10n.ui("reminder.confirm", defaultValue: "Confirm date and enable reminder")) { scheduleReminder() }
            Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { pendingReminder = nil }
        } message: {
            Text(reminderExplanation)
        }
        .alert(L10n.ui("reminder.title", defaultValue: "Reminder"), isPresented: Binding(get: { actionMessage != nil }, set: { if !$0 { actionMessage = nil } })) {
            Button(L10n.ui("common.ok", defaultValue: "OK"), role: .cancel) { actionMessage = nil }
        } message: { Text(actionMessage ?? "") }
    }

    @ViewBuilder private var readinessSummary: some View {
        let checked = documents.compactMap { model.readiness[$0.id] }
        if !checked.isEmpty {
            let ready = checked.filter { $0.state == .ready }.count
            Label(L10n.ui("readiness.summary", defaultValue: "\(ready) of \(documents.count) originals verified"),
                systemImage: ready == documents.count ? "checkmark.circle.fill" : "exclamationmark.circle")
                .font(.footnote.weight(.medium))
                .foregroundStyle(ready == documents.count ? TripStyle.accent : .orange)
            if let last = checked.map(\.checkedAt).max() {
                Text(L10n.ui("readiness.last", defaultValue: "Last check: \(L10n.date(last, date: .abbreviated, time: .shortened))"))
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var reminderExplanation: String {
        guard let date = pendingReminder?.expiryDate else { return L10n.ui("reminder.noDate", defaultValue: "Confirm the expiry date on the original document first.") }
        return L10n.ui("reminder.explanation", defaultValue: "Confirm that \(L10n.date(TravelDate.local(from: date))) matches the original document. A generic notification is scheduled 30 days before at 9 AM in the time zone used when scheduled, or the next 9 AM in that zone before expiry if closer. Traveling to another time zone does not automatically move this reminder. Delivery depends on your device settings.")
    }

    private func addDocument() {
        if model.canAddDocument { showsImport = true } else { showsPro = true }
    }
    private func toggleSelection(_ id: UUID) {
        if selectedIDs.contains(id) { selectedIDs.remove(id) } else { selectedIDs.insert(id) }
    }
    private func open(_ document: TravelDocument) {
        Task {
            if let url = await model.previewURL(documentID: document.id) {
                previewCleanupURL = url
                preview = PresentedFile(url: url)
            }
        }
    }
    private func scheduleReminder() {
        guard let document = pendingReminder else { return }
        pendingReminder = nil
        guard model.purchases.isPro else { showsPro = true; return }
        Task {
            do {
                try await ReminderService.schedule(document: document,
                    travelerName: model.library.travelers.first { $0.id == document.travelerID }?.name,
                    canSchedule: { model.purchases.isPro },
                    isCurrentDocument: { model.library.documents.contains(document) })
                actionMessage = L10n.ui("reminder.scheduled", defaultValue: "Reminder scheduled. You can manage notification permissions in iOS Settings.")
            } catch { actionMessage = error.localizedDescription }
        }
    }
}

private struct DocumentRow: View {
    let document: TravelDocument
    let traveler: String?
    let readiness: DocumentReadiness?
    let selection: Bool?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: selection.map { $0 ? "checkmark.circle.fill" : "circle" } ?? document.kind.symbol)
                .font(.title2).foregroundStyle(TripStyle.accent).frame(width: 30)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 5) {
                Text(document.title).font(.headline).foregroundStyle(.primary)
                Text([document.kind.displayName, traveler].compactMap { $0 }.joined(separator: " · "))
                    .font(.subheadline).foregroundStyle(.secondary)
                if let storedDate = document.expiryDate {
                    let date = TravelDate.local(from: storedDate)
                    let expired = Calendar.current.startOfDay(for: date) < Calendar.current.startOfDay(for: Date())
                    Label(expired ? L10n.ui("document.expired", defaultValue: "Expired \(L10n.date(date))") : L10n.ui("document.expires", defaultValue: "Expires \(L10n.date(date))"), systemImage: expired ? "exclamationmark.triangle" : "calendar")
                        .font(.caption).foregroundStyle(expired ? .red : .secondary)
                }
                Label(readinessLabel, systemImage: readinessSymbol)
                    .font(.caption.weight(.medium)).foregroundStyle(readinessColor)
                Text(L10n.byteCount(Int64(document.byteCount)))
                    .font(.caption2).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }.padding(.vertical, 7)
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(selection == true ? [.isSelected] : [])
    }
    private var readinessLabel: String {
        switch readiness?.state {
        case .ready: L10n.ui("readiness.ready", defaultValue: "Original verified")
        case .missing: L10n.ui("readiness.missing", defaultValue: "Original missing — import it again")
        case .modified: L10n.ui("readiness.modified", defaultValue: "Original changed — restore a good copy")
        case .unreadable: L10n.ui("readiness.unreadable", defaultValue: "Original couldn’t be read — retry check")
        case nil: L10n.ui("readiness.unchecked", defaultValue: "Not checked")
        }
    }
    private var readinessSymbol: String {
        switch readiness?.state {
        case .ready: "checkmark.circle.fill"
        case .missing, .modified, .unreadable: "exclamationmark.triangle"
        case nil: "circle.dashed"
        }
    }
    private var readinessColor: Color {
        switch readiness?.state {
        case .ready: TripStyle.accent
        case .missing, .modified, .unreadable: .orange
        case nil: .secondary
        }
    }
}

private struct ImportDocumentView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let tripID: UUID
    @State private var title = ""
    @State private var kind: DocumentKind = .other
    @State private var travelerID: UUID?
    @State private var hasExpiry = false
    @State private var expiryDate = Date()
    @State private var fileURL: URL?
    @State private var scannedData: Data?
    @State private var filename = ""
    @State private var showsFiles = false
    @State private var showsScanner = false
    @State private var recognizing = false
    @State private var recognizedText = ""
    @State private var localError: String?

    private var hasSource: Bool { fileURL != nil || scannedData != nil }
    private var busy: Bool { recognizing || model.isBusy }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Button { showsFiles = true } label: { Label(L10n.ui("import.files", defaultValue: "Import from Files"), systemImage: "folder") }
                        .disabled(busy)
                    if DocumentScanner.isSupported {
                        Button { showsScanner = true } label: { Label(L10n.ui("import.scan", defaultValue: "Scan paper document"), systemImage: "doc.viewfinder") }
                            .disabled(busy)
                    } else {
                        Label(L10n.ui("import.scanUnsupported", defaultValue: "Scanning needs a supported device"), systemImage: "doc.viewfinder")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    if hasSource {
                        Label(filename, systemImage: "checkmark.circle.fill")
                            .font(.subheadline).foregroundStyle(TripStyle.accent)
                    }
                } header: { Text(L10n.ui("original.file", defaultValue: "Original file")) } footer: {
                    Text(L10n.ui("import.help", defaultValue: "PDF, JPEG or PNG, up to 16 MB each. Import copies the full file into TripDocket. Files stored in a cloud provider may need internet to download first."))
                }
                if hasSource {
                    Section(L10n.ui("document.details", defaultValue: "Document details")) {
                        TextField(L10n.ui("document.title", defaultValue: "Document title"), text: $title).accessibilityLabel(L10n.ui("document.title", defaultValue: "Document title"))
                        Picker(L10n.ui("document.type", defaultValue: "Type"), selection: $kind) {
                            ForEach(DocumentKind.allCases, id: \.self) { kind in
                                Text(kind.displayName).tag(kind)
                            }
                        }
                        Picker(L10n.ui("document.person", defaultValue: "Person"), selection: $travelerID) {
                            Text(L10n.ui("document.unassigned", defaultValue: "Everyone / unassigned")).tag(Optional<UUID>.none)
                            ForEach(model.library.travelers, id: \.id) { traveler in
                                Text(traveler.name).tag(Optional(traveler.id))
                            }
                        }
                        Toggle(L10n.ui("document.addExpiry", defaultValue: "Add confirmed expiry date"), isOn: $hasExpiry)
                        if hasExpiry {
                            DatePicker(L10n.ui("document.expiry", defaultValue: "Expiry date"), selection: $expiryDate, displayedComponents: .date)
                            Text(L10n.ui("document.dateHelp", defaultValue: "Check the date against the original. TripDocket does not determine whether this document meets travel requirements."))
                                .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Section {
                        Button(action: recognizeText) {
                            HStack {
                                Label(recognizing ? L10n.ui("ocr.working", defaultValue: "Reading text on this device…") : L10n.ui("ocr.action", defaultValue: "Find text on this device"), systemImage: "text.viewfinder")
                                if recognizing { Spacer(); ProgressView() }
                            }
                        }.disabled(busy)
                        if !recognizedText.isEmpty {
                            TextEditor(text: $recognizedText).frame(minHeight: 150)
                                .accessibilityLabel(L10n.ui("ocr.editorAX", defaultValue: "Recognized text, editable suggestion"))
                            Button(L10n.ui("ocr.useTitle", defaultValue: "Use first line as title")) {
                                if let first = recognizedText.split(whereSeparator: \.isNewline).first {
                                    title = String(first.prefix(160))
                                }
                            }
                        }
                    } header: { Text(L10n.ui("ocr.section", defaultValue: "Optional text recognition")) } footer: {
                        Text(L10n.ui("ocr.help", defaultValue: "Suggestions can be wrong. Edit them before use. Only the title you choose is saved; the extracted text is discarded. Recognition checks up to the first 3 PDF pages and never fills in dates."))
                    }
                }
                if let localError {
                    Section { Label(localError, systemImage: "exclamationmark.triangle").foregroundStyle(.red).font(.footnote) }
                }
                InlineErrorRow()
            }
            .navigationTitle(L10n.ui("document.importTitle", defaultValue: "Add document")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(L10n.ui("common.cancel", defaultValue: "Cancel")) { dismiss() }.disabled(busy) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.ui("common.save", defaultValue: "Save"), action: save)
                        .disabled(!hasSource || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || busy)
                }
            }
            .interactiveDismissDisabled(busy)
            .fileImporter(isPresented: $showsFiles, allowedContentTypes: [.pdf, .jpeg, .png], allowsMultipleSelection: false) { result in
                do {
                    guard let url = try result.get().first else { return }
                    fileURL = url; scannedData = nil; filename = url.lastPathComponent
                    title = url.deletingPathExtension().lastPathComponent
                    recognizedText = ""; localError = nil
                } catch { localError = error.localizedDescription }
            }
            .fullScreenCover(isPresented: $showsScanner) {
                DocumentScanner { result in
                    showsScanner = false
                    switch result {
                    case .success(let data):
                        scannedData = data; fileURL = nil; filename = "Scanned document.pdf"
                        title = L10n.ui("scan.defaultTitle", defaultValue: "Scanned document"); recognizedText = ""; localError = nil
                    case .failure(let error): localError = error.localizedDescription
                    }
                } onCancel: { showsScanner = false }
                    .ignoresSafeArea()
            }
        }
    }

    private func recognizeText() {
        recognizing = true
        localError = nil
        Task {
            defer { recognizing = false }
            do {
                if let scannedData { recognizedText = try await OCRService.recognizeText(in: scannedData) }
                else if let fileURL {
                    recognizedText = try await OCRService.recognizeText(at: fileURL)
                }
            } catch { localError = error.localizedDescription }
        }
    }

    private func save() {
        Task {
            let count = model.library.documents.count
            let cleanedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
            if let scannedData {
                await model.importData(scannedData, filename: filename, tripID: tripID, travelerID: travelerID,
                    title: cleanedTitle, kind: kind, expiryDate: hasExpiry ? expiryDate : nil)
            } else if let fileURL {
                await model.importFile(url: fileURL, tripID: tripID, travelerID: travelerID,
                    title: cleanedTitle, kind: kind, expiryDate: hasExpiry ? expiryDate : nil)
            }
            if model.library.documents.count > count { dismiss() }
        }
    }
}

private struct TravelersView: View {
    @Environment(AppModel.self) private var model
    @State private var showsNewPerson = false
    @State private var showsPro = false
    @State private var name = ""
    @State private var editingPerson: Traveler?
    @State private var deletingPerson: Traveler?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(L10n.ui("people.intro", defaultValue: "Make it easy to find the right person’s passport, ticket or insurance."))
                        .foregroundStyle(.secondary)
                }
                if model.library.travelers.isEmpty {
                    Section {
                        ContentUnavailableView {
                            Label(L10n.ui("people.empty", defaultValue: "Who’s coming?"), systemImage: "person.2")
                        } description: { Text(L10n.ui("people.emptyHelp", defaultValue: "Add a name or nickname, then choose that person when importing a document.")) }
                        actions: { Button(L10n.ui("person.addEmpty", defaultValue: "Add a person"), action: addPerson).buttonStyle(.borderedProminent) }
                    }
                } else {
                    Section(L10n.ui("people.section", defaultValue: "People in your library")) {
                        ForEach(model.library.travelers, id: \.id) { person in
                            Button { editingPerson = person } label: {
                                HStack(spacing: 12) {
                                    Image(systemName: "person.crop.circle.fill")
                                        .font(.title).foregroundStyle(TripStyle.accent).accessibilityHidden(true)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(person.name).font(.headline)
                                        let count = model.library.documents.filter { $0.travelerID == person.id }.count
                                        Text(L10n.ui("count.documents", defaultValue: "\(count) documents"))
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Image(systemName: "pencil").font(.caption).foregroundStyle(.secondary)
                                }.padding(.vertical, 5)
                            }
                            .buttonStyle(.plain)
                            .accessibilityHint(L10n.ui("person.editAX", defaultValue: "Edit this person’s name"))
                            .contextMenu {
                                Button(L10n.ui("person.edit", defaultValue: "Edit person"), systemImage: "pencil") { editingPerson = person }
                                Button(L10n.ui("person.delete", defaultValue: "Delete person"), systemImage: "trash", role: .destructive) { deletingPerson = person }
                            }
                            .swipeActions {
                                Button(L10n.ui("common.delete", defaultValue: "Delete"), role: .destructive) { deletingPerson = person }
                            }
                            .accessibilityAction(named: L10n.ui("person.delete", defaultValue: "Delete person")) { deletingPerson = person }
                        }
                    }
                }
            }
            .navigationTitle(L10n.ui("nav.people", defaultValue: "People"))
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: addPerson) { Label(L10n.ui("person.add", defaultValue: "Add person"), systemImage: "person.badge.plus") }.disabled(model.isBusy)
                }
            }
            .alert(L10n.ui("person.addEmpty", defaultValue: "Add a person"), isPresented: $showsNewPerson) {
                TextField(L10n.ui("person.name", defaultValue: "Name or nickname"), text: $name)
                Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { name = "" }
                Button(L10n.ui("common.add", defaultValue: "Add")) {
                    let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
                    name = ""
                    Task { await model.addTraveler(name: value) }
                }.disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } message: { Text(L10n.ui("person.nameHelp", defaultValue: "Use a name you’ll recognize. A legal name is not required.")) }
            .sheet(isPresented: $showsPro) { ProView() }
            .sheet(item: $editingPerson) { person in EditTravelerView(person: person) }
            .confirmationDialog(L10n.ui("person.deleteTitle", defaultValue: "Delete this person?"), isPresented: Binding(
                get: { deletingPerson != nil }, set: { if !$0 { deletingPerson = nil } }
            ), titleVisibility: .visible) {
                Button(L10n.ui("person.delete", defaultValue: "Delete person"), role: .destructive) {
                    guard let person = deletingPerson else { return }
                    deletingPerson = nil
                    Task { await model.deleteTraveler(id: person.id) }
                }
                Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { deletingPerson = nil }
            } message: {
                Text(L10n.ui("person.deleteBody", defaultValue: "“\(deletingPerson?.name ?? L10n.ui("person.fallback", defaultValue: "This person"))” will be removed. Their documents are kept in their trips and become unassigned. Previously exported copies keep their old details."))
            }
        }
    }
    private func addPerson() {
        if model.canAddTraveler { showsNewPerson = true } else { showsPro = true }
    }
}

private struct EditTravelerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let person: Traveler
    @State private var name: String

    init(person: Traveler) {
        self.person = person
        _name = State(initialValue: person.name)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section(L10n.ui("person.details", defaultValue: "Person details")) {
                    TextField(L10n.ui("person.name", defaultValue: "Name or nickname"), text: $name).textInputAutocapitalization(.words)
                        .accessibilityLabel(L10n.ui("person.name", defaultValue: "Name or nickname"))
                }
                Section {
                    Text(L10n.ui("person.editHelp", defaultValue: "Documents stay assigned to this person when you change their name."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                InlineErrorRow()
            }
            .navigationTitle(L10n.ui("person.edit", defaultValue: "Edit person")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(L10n.ui("common.cancel", defaultValue: "Cancel")) { dismiss() }.disabled(model.isBusy) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.ui("common.save", defaultValue: "Save")) {
                        let value = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        Task {
                            model.errorMessage = nil
                            await model.updateTraveler(id: person.id, name: value)
                            if model.errorMessage == nil, model.library.travelers.first(where: { $0.id == person.id })?.name == value { dismiss() }
                        }
                    }.disabled(model.isBusy || name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }.interactiveDismissDisabled(model.isBusy)
        }
    }
}

private struct EditDocumentView: View {
    @Environment(AppModel.self) private var model
    @Bindable var draft: DocumentEditDraft

    var body: some View {
        NavigationStack {
            Form {
                Section(L10n.ui("document.details", defaultValue: "Document details")) {
                    TextField(L10n.ui("document.title", defaultValue: "Document title"), text: $draft.title).accessibilityLabel(L10n.ui("document.title", defaultValue: "Document title"))
                    Picker(L10n.ui("document.type", defaultValue: "Type"), selection: $draft.kind) {
                        ForEach(DocumentKind.allCases, id: \.self) { kind in Text(kind.displayName).tag(kind) }
                    }
                    Picker(L10n.ui("document.person", defaultValue: "Person"), selection: $draft.travelerID) {
                        Text(L10n.ui("document.unassigned", defaultValue: "Everyone / unassigned")).tag(Optional<UUID>.none)
                        ForEach(model.library.travelers, id: \.id) { person in Text(person.name).tag(Optional(person.id)) }
                    }
                    Toggle(L10n.ui("document.confirmedExpiry", defaultValue: "Confirmed expiry date"), isOn: $draft.hasExpiry)
                    if draft.hasExpiry {
                        DatePicker(L10n.ui("document.expiry", defaultValue: "Expiry date"), selection: $draft.expiryDate, displayedComponents: .date)
                    }
                }
                Section {
                    Text(L10n.ui("document.editDateHelp", defaultValue: "Check the expiry date against the original document. After saving, enable its reminder again if you need one; the previous reminder is removed so it cannot use outdated details."))
                        .font(.footnote).foregroundStyle(.secondary)
                    Label(L10n.ui("document.originalKept", defaultValue: "The saved original file stays unchanged"), systemImage: "doc")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                InlineErrorRow()
            }
            .navigationTitle(L10n.ui("document.edit", defaultValue: "Edit document")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L10n.ui("common.cancel", defaultValue: "Cancel")) { model.cancelDocumentEdit() }.disabled(model.isBusy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.ui("common.save", defaultValue: "Save")) {
                        Task { await model.saveDocumentEdit() }
                    }.disabled(model.isBusy || draft.title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }.interactiveDismissDisabled()
        }
    }
}

private struct TripDeletionConfirmation: ViewModifier {
    @Environment(AppModel.self) private var model
    @Binding var pendingTrip: Trip?
    var didDelete: () -> Void = {}

    func body(content: Content) -> some View {
        content.confirmationDialog(L10n.ui("trip.deleteTitle", defaultValue: "Delete this trip and its originals?"), isPresented: Binding(
            get: { pendingTrip != nil }, set: { if !$0 { pendingTrip = nil } }
        ), titleVisibility: .visible) {
            Button(L10n.ui("trip.deleteConfirm", defaultValue: "Delete trip and documents"), role: .destructive) {
                guard let trip = pendingTrip else { return }
                pendingTrip = nil
                Task {
                    await model.deleteTrip(id: trip.id)
                    if !model.library.trips.contains(where: { $0.id == trip.id }) { didDelete() }
                }
            }
            Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { pendingTrip = nil }
        } message: {
            let count = model.library.documents.filter { $0.tripID == pendingTrip?.id }.count
            Text(L10n.ui("trip.deleteBody", defaultValue: "“\(pendingTrip?.title ?? L10n.ui("trip.thisFallback", defaultValue: "This trip"))” and its \(count) original documents will be removed from this device’s library. Export the trip first if you need to keep a copy. People and previously exported copies remain."))
        }
    }
}

private struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var showsPro = false
    @State private var asksBackup = false
    @State private var showsRestoreFiles = false
    @State private var pendingRestore: URL?
    @State private var share: PresentedFile?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink { PrivacySupportView() } label: {
                        Label(L10n.ui("settings.privacySupport", defaultValue: "Privacy & support"), systemImage: "hand.raised")
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .accessibilityIdentifier("privacySupport.entry")
                }
                Section {
                    Button { showsPro = true } label: {
                        HStack(alignment: .top, spacing: 12) {
                            Image(systemName: "sparkles").font(.title2)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(model.purchases.isPro ? L10n.ui("brand.pro", defaultValue: "TripDocket Pro") : L10n.ui("pro.settingsTitle", defaultValue: "Make room for every trip")).font(.headline)
                                Text(model.purchases.isPro ? L10n.ui("pro.settingsActive", defaultValue: "Pro is unlocked on this device.") : L10n.ui("pro.settingsBody", defaultValue: "More trips, people and documents. One-time purchase."))
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption)
                        }.padding(.vertical, 8)
                    }
                    Button(L10n.ui("pro.restore", defaultValue: "Restore purchases")) { Task { await model.purchases.restore() } }
                        .disabled(model.purchases.isBusy)
                    if let status = model.purchases.statusMessage { Text(status).font(.footnote).foregroundStyle(.secondary) }
                }
                Section {
                    Button { asksBackup = true } label: { Label(L10n.ui("backup.export", defaultValue: "Export full backup"), systemImage: "square.and.arrow.up") }
                        .disabled(model.isBusy)
                    Button { showsRestoreFiles = true } label: { Label(L10n.ui("backup.restore", defaultValue: "Restore from backup"), systemImage: "square.and.arrow.down") }
                        .disabled(model.isBusy)
                } header: { Text(L10n.ui("backup.section", defaultValue: "Backup & recovery")) } footer: {
                    Text(L10n.ui("backup.help", defaultValue: "TripDocket has no account or cloud sync. Export a backup to a place you trust before deleting the app or changing devices. A successful restore replaces the entire current library. Viewing, export and recovery do not require Pro."))
                }
                Section(L10n.ui("settings.device", defaultValue: "On this device")) {
                    LabeledContent(L10n.ui("nav.trips", defaultValue: "Trips"), value: model.library.trips.count.formatted(.number.locale(L10n.formattingLocale())))
                    LabeledContent(L10n.ui("nav.people", defaultValue: "People"), value: model.library.travelers.count.formatted(.number.locale(L10n.formattingLocale())))
                    LabeledContent(L10n.ui("documents.title", defaultValue: "Documents"), value: model.library.documents.count.formatted(.number.locale(L10n.formattingLocale())))
                    LabeledContent(L10n.ui("settings.originals", defaultValue: "Original files"), value: L10n.byteCount(Int64(model.library.documents.reduce(0) { $0 + $1.byteCount })))
                }
                Section(L10n.ui("settings.privacy", defaultValue: "Privacy & safe keeping")) {
                    Button(L10n.ui("settings.lock", defaultValue: "Lock now"), systemImage: "lock") {
                        NotificationCenter.default.post(name: .tripfolioLockNow, object: nil)
                    }
                    Label(L10n.ui("settings.local", defaultValue: "Local processing, no account required"), systemImage: "iphone")
                    Label(L10n.ui("settings.authentication", defaultValue: "Device authentication protects app access"), systemImage: "lock.shield")
                    Text(L10n.ui("settings.protectionHelp", defaultValue: "Keep a device passcode enabled. Documents use iOS file protection; exported packets are unencrypted copies outside the app’s protection. Share only with recipients and destinations you trust."))
                        .font(.footnote).foregroundStyle(.secondary)
                    Text(L10n.ui("settings.dateHelp", defaultValue: "Dates are entered and confirmed by you. Expiry reminders are a convenience, not a check of entry requirements or document validity for a destination."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                NoticeRow()
            }
            .navigationTitle(L10n.ui("nav.settings", defaultValue: "Settings"))
            .sheet(isPresented: $showsPro) { ProView() }
            .sheet(item: $share) { file in
                ExplicitShareSheet(url: file.url) { model.removeTemporary(file.url) }
            }
            .confirmationDialog(L10n.ui("backup.warning.title", defaultValue: "Export an unencrypted backup?"), isPresented: $asksBackup, titleVisibility: .visible) {
                Button(L10n.ui("common.export", defaultValue: "Export…")) {
                    Task {
                        if let url = await model.makeBackup(documentIDs: nil) {
                            share = PresentedFile(url: url)
                        }
                    }
                }
                Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) {}
            } message: {
                Text(L10n.ui("backup.warning.body", defaultValue: "The backup includes every original document, person and trip in readable, unencrypted form. Anyone with a copy can access them. Keep it in a trusted location. Previously shared copies cannot be revoked."))
            }
            .fileImporter(isPresented: $showsRestoreFiles, allowedContentTypes: [.data, .json], allowsMultipleSelection: false) { result in
                do { pendingRestore = try result.get().first }
                catch { model.errorMessage = error.localizedDescription }
            }
            .confirmationDialog(L10n.ui("backup.replaceTitle", defaultValue: "Replace your entire library?"), isPresented: Binding(
                get: { pendingRestore != nil }, set: { if !$0 { pendingRestore = nil } }
            ), titleVisibility: .visible) {
                Button(L10n.ui("backup.replace", defaultValue: "Replace library from backup"), role: .destructive) {
                    guard let url = pendingRestore else { return }
                    pendingRestore = nil
                    Task { await model.restoreBackup(url: url) }
                }
                Button(L10n.ui("common.cancel", defaultValue: "Cancel"), role: .cancel) { pendingRestore = nil }
            } message: {
                Text(L10n.ui("backup.replaceBody", defaultValue: "This will replace all \(model.library.documents.count) current documents, trips and people with the selected backup. Export your current library first if you need to keep it. The backup is validated before replacement; a failed restore keeps your current library."))
            }
        }
    }
}

private struct ProView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 14) {
                        Image(systemName: "suitcase.rolling.fill").font(.largeTitle).foregroundStyle(TripStyle.accent)
                            .accessibilityHidden(true)
                        Text(model.purchases.isPro ? L10n.ui("pro.activeHero", defaultValue: "Every trip has a place.") : L10n.ui("pro.hero", defaultValue: "A little more room\nfor the journey."))
                            .font(.system(.largeTitle, design: .rounded, weight: .bold))
                            .fixedSize(horizontal: false, vertical: true)
                        Text(L10n.ui("brand.pro", defaultValue: "TripDocket Pro")).font(.headline).foregroundStyle(TripStyle.accent)
                        Text(L10n.ui("pro.intro", defaultValue: "A one-time purchase for the people and trips you keep coming back to."))
                            .foregroundStyle(.secondary)
                    }.padding(.vertical)
                }.listRowBackground(TripStyle.tint.opacity(0.4))
                Section(L10n.ui("pro.includes", defaultValue: "Pro includes")) {
                    Label(L10n.ui("pro.more", defaultValue: "More trips, people and documents"), systemImage: "square.stack.3d.up")
                    Label(L10n.ui("pro.batch", defaultValue: "Import up to 10 files together, with individual review"), systemImage: "doc.on.doc")
                    Label(L10n.ui("pro.reminders", defaultValue: "Expiry reminders you explicitly enable"), systemImage: "bell.badge")
                    Text(L10n.ui("pro.limit", defaultValue: "The device library supports up to 64 MB of original files, with a 16 MB limit per file."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    if model.purchases.isPro {
                        Label(L10n.ui("pro.unlocked", defaultValue: "Pro is unlocked"), systemImage: "checkmark.seal.fill").foregroundStyle(TripStyle.accent)
                    } else {
                        Button {
                            Task { await model.purchases.purchase() }
                        } label: {
                            HStack {
                                Spacer()
                                if model.purchases.isBusy { ProgressView() }
                                Text(model.purchases.displayPrice.map { L10n.ui("pro.price", defaultValue: "Unlock Pro · \($0)") } ?? L10n.ui("pro.noPrice", defaultValue: "Price unavailable"))
                                    .font(.headline)
                                Spacer()
                            }.padding(.vertical, 8)
                        }.buttonStyle(.borderedProminent)
                            .disabled(model.purchases.isBusy || model.purchases.displayPrice == nil)
                        Text(L10n.ui("pro.oneTime", defaultValue: "One-time purchase. No subscription.")).font(.footnote).foregroundStyle(.secondary)
                    }
                    Button(L10n.ui("pro.restore", defaultValue: "Restore purchases")) { Task { await model.purchases.restore() } }
                        .disabled(model.purchases.isBusy)
                    if model.purchases.displayPrice == nil && !model.purchases.isPro {
                        Button(L10n.ui("pro.retryPrice", defaultValue: "Retry loading price")) { Task { await model.purchases.load() } }
                            .disabled(model.purchases.isBusy)
                    }
                    if let status = model.purchases.statusMessage {
                        Text(status).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section {
                    Text(L10n.ui("pro.freeHelp", defaultValue: "Free includes one trip, two people and eight documents. Your existing documents always remain available to view, export, delete and restore, even if Pro is no longer active."))
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle(L10n.ui("brand.pro", defaultValue: "TripDocket Pro")).navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button(L10n.ui("common.done", defaultValue: "Done")) { dismiss() } } }
            .task { await model.purchases.load() }
        }
    }
}

struct PreviewSheet: View {
    @Environment(\.dismiss) private var dismiss
    let url: URL
    var body: some View {
        NavigationStack {
            DocumentPreview(url: url)
                .safeAreaInset(edge: .bottom) {
                    Label(L10n.ui("preview.shareWarning", defaultValue: "Sharing from this preview sends an unencrypted original. Choose a trusted recipient; sent copies cannot be revoked."), systemImage: "lock.open")
                        .font(.footnote).foregroundStyle(.secondary).padding()
                        .frame(maxWidth: .infinity).background(.regularMaterial)
                }
                .navigationTitle(L10n.ui("preview.title", defaultValue: "Original document")).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button(L10n.ui("common.done", defaultValue: "Done")) { dismiss() } } }
        }
    }
}

private struct NoticeRow: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let notice = model.notice {
            Section {
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "info.circle").foregroundStyle(TripStyle.accent).accessibilityHidden(true)
                    Text(notice).font(.footnote)
                    Spacer(minLength: 0)
                    Button { model.notice = nil } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
                        .accessibilityLabel(L10n.ui("notice.dismiss", defaultValue: "Dismiss notice"))
                }
            }
        }
    }
}

private struct InlineErrorRow: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        if let message = model.errorMessage {
            Section { Label(message, systemImage: "exclamationmark.triangle").font(.footnote).foregroundStyle(.red) }
        }
    }
}

private struct PresentedFile: Identifiable {
    let id = UUID()
    let url: URL
}

private extension DocumentKind {
    var symbol: String {
        switch self {
        case .passport: "person.text.rectangle"
        case .insurance: "cross.case"
        case .ticket: "ticket"
        case .booking: "bed.double"
        case .other: "doc.text"
        }
    }
}
