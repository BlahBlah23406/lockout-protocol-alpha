import FamilyControls
import ManagedSettings
import SwiftUI

/// "What are you working on?" — the start flow, in two steps.
///
/// Step one is the same everywhere: type the task, pick a length and a level. Step two is
/// iOS-only and exists because the decision here is coarser than on the other platforms — the
/// model picks whole apps to shut, so the user gets to see and correct that list before it takes
/// effect. On the desktop a wrong call costs one interrupted moment; here it costs an app being
/// shut for ninety minutes, so it is worth one confirmation screen.
struct FocusStartView: View {
    var onStarted: () -> Void
    var onCancel: () -> Void

    @StateObject private var prefs = Prefs.shared
    @StateObject private var sessions = SessionStore.shared
    @StateObject private var shield = ShieldController.shared

    @State private var task = ""
    @State private var minutes = 50
    @State private var accountability: Accountability = .selfManaged
    @State private var selection = FamilyActivitySelection()
    @State private var showingPicker = false

    /// Step two: the plan the model proposed, awaiting confirmation.
    @State private var plan: ShieldPlan.Decision?
    @State private var candidates: [ShieldPlan.Candidate] = []
    @State private var thinking = false
    @State private var error = ""

    private static let durations: [(Int, String)] = [(25, "25m"), (50, "50m"), (90, "90m"),
                                                     (0, "open")]

    var body: some View {
        NavigationStack {
            Form {
                if let plan {
                    planSection(plan)
                } else {
                    taskSection
                    lengthSection
                    accountabilitySection
                    appsSection
                }
                if !error.isEmpty {
                    Section { Text(error).foregroundStyle(.red).font(.callout) }
                }
            }
            .navigationTitle(plan == nil ? "Focus session" : "Confirm the plan")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { plan == nil ? onCancel() : (plan = nil) }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if thinking {
                        ProgressView()
                    } else if plan == nil {
                        Button("Next") { Task { await propose() } }
                    } else {
                        Button("Start") { start() }
                    }
                }
            }
            .familyActivityPicker(isPresented: $showingPicker, selection: $selection)
            .onAppear {
                task = prefs.lastTask
                minutes = prefs.focusMinutes
                accountability = prefs.focusAccountability
                selection = prefs.savedSelection
            }
        }
    }

    // MARK: - Step one

    private var taskSection: some View {
        Section {
            TextField("e.g. revising integration by parts for Friday's test",
                      text: $task, axis: .vertical)
                .lineLimit(2...4)
        } header: {
            Text("I am working on")
        } footer: {
            Text("Plain English. The model reads this exactly as you write it, so be specific — "
                 + "it decides which of your apps to shut based on nothing else.")
        }
    }

    private var lengthSection: some View {
        Section("For") {
            Picker("Length", selection: $minutes) {
                ForEach(Self.durations, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.segmented)
        }
    }

    private var accountabilitySection: some View {
        Section {
            ForEach(Accountability.allCases, id: \.self) { level in
                Button {
                    accountability = level
                } label: {
                    HStack(alignment: .top) {
                        Image(systemName: accountability == level
                              ? "largecircle.fill.circle" : "circle")
                        VStack(alignment: .leading, spacing: 2) {
                            Text(level.title).font(.body.weight(.semibold))
                            Text(level.blurb).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        } header: {
            Text("Accountability")
        } footer: {
            if let warning = lockedWarning {
                // Say the awkward part out loud before they commit, not after.
                Text("⚠ " + warning).foregroundStyle(.orange)
            }
        }
    }

    private var lockedWarning: String? {
        guard accountability == .locked else { return nil }
        var problems: [String] = []
        if !prefs.pinSet {
            problems.append("no passcode is set yet — set one in Settings first, or unshielding "
                          + "will need no code at all")
        }
        if !prefs.pushEnabled {
            problems.append("alerts are off, so nobody will actually be told")
        }
        // On iOS an unshield can only be done from inside the app, so a locked session has one
        // extra thing worth knowing before you start it.
        problems.append("unshielding a locked session has to be done here in Lockout — the shield "
                      + "screen itself can't ask for a passcode")
        return problems.joined(separator: "; ")
    }

    private var appsSection: some View {
        Section {
            Button {
                showingPicker = true
            } label: {
                HStack {
                    Text("Choose apps")
                    Spacer()
                    Text("\(selection.applicationTokens.count) offered")
                        .foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Apps")
        } footer: {
            Text("Pick the apps you're willing to have shut. iOS never tells this app what they "
                 + "are — it hands over sealed references only the system can open — so the "
                 + "picker is the only way to choose them, and nothing else can read the list.")
        }
    }

    // MARK: - Step two

    private func planSection(_ plan: ShieldPlan.Decision) -> some View {
        Group {
            Section {
                Text(task).font(.body.weight(.semibold))
            } header: {
                Text("You said")
            }

            Section {
                Text(plan.reasoning).font(.callout)
            } header: {
                Text(plan.isFallback ? "No model answer" : "The model's reasoning")
            } footer: {
                if plan.isFallback {
                    Text("Everything you offered will be shut. That's the safe default when the "
                         + "model can't be reached — unlike a block screen, a shield can't lock "
                         + "you out of anything: iOS never shields the home screen, Settings, "
                         + "Phone, or Messages.")
                }
            }

            Section {
                LabeledContent("Shut") { Text("\(plan.shield.count) app(s)") }
                LabeledContent("Left open") { Text("\(plan.allow.count) app(s)") }
                LabeledContent("For") {
                    Text(minutes == 0 ? "open-ended" : "\(minutes) minutes")
                }
                LabeledContent("Level") { Text(accountability.title) }
            } footer: {
                Text("iOS won't let this app show you which is which by name — the tokens are "
                     + "opaque. If the counts look wrong, go back and change what you offered.")
            }
        }
    }

    // MARK: - Actions

    private func propose() async {
        error = ""
        let trimmed = task.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.count >= 3 else {
            error = "Tell it what you're working on first."
            return
        }
        guard accountability != .locked || minutes > 0 else {
            error = "A locked session needs an end time — open-ended locked sessions aren't allowed."
            return
        }
        guard !selection.applicationTokens.isEmpty else {
            error = "Choose at least one app you're willing to have shut."
            return
        }
        if let problem = shield.diagnose().first {
            error = problem
            return
        }

        thinking = true
        defer { thinking = false }

        // Build the candidate list. The label is whatever the system will tell us, which is often
        // nothing — `ShieldPlan` handles the unnamed case explicitly.
        candidates = selection.applicationTokens.compactMap { token in
            guard let encoded = ShieldController.encode(token: token) else { return nil }
            return ShieldPlan.Candidate(token: encoded,
                                        label: Application(token: token).localizedDisplayName ?? "")
        }

        plan = await ShieldPlan.decide(task: trimmed, candidates: candidates,
                                       config: prefs.providerConfig(),
                                       extraNotes: prefs.focusNotes)
    }

    private func start() {
        guard let plan else { return }
        let trimmed = task.trimmingCharacters(in: .whitespacesAndNewlines)

        let session = FocusSession(task: trimmed, plannedMinutes: minutes,
                                   intervalSeconds: prefs.focusInterval,
                                   accountability: accountability,
                                   shieldedTokens: plan.shield,
                                   providerId: prefs.providerId)

        // Remember the answers so next time is one tap.
        prefs.lastTask = trimmed
        prefs.focusMinutes = minutes
        prefs.focusAccountability = accountability
        prefs.savedSelection = selection

        sessions.start(session)
        shield.apply(tokens: plan.shield)
        shield.schedule(until: session.endsAt)
        Judgements.recordSessionStart(session, plan: plan, provider: prefs.providerConfig().describe)
        onStarted()
    }
}
