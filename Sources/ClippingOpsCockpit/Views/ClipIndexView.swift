import SwiftUI

struct ClipIndexView: View {
    @ObservedObject var store: OpsStore
    @State private var searchText = ""

    private var filteredClips: [ClipCandidate] {
        guard !searchText.isEmpty else { return store.clips }
        return store.clips.filter {
            $0.title.localizedCaseInsensitiveContains(searchText)
            || $0.provenance.localizedCaseInsensitiveContains(searchText)
            || $0.localMediaPath.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Clip Index", subtitle: "Agent workbench view of campaign candidates, provenance, source state, and local media.")
                .padding(22)
            if filteredClips.isEmpty {
                EmptyStateView(title: "No Campaign Clips Indexed", message: "Discover source-backed campaigns, then build only evidence-backed campaign reviews.", systemImage: "film.stack")
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        ForEach(filteredClips) { clip in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(alignment: .firstTextBaseline) {
                                    Text(clip.title)
                                        .font(.headline)
                                        .lineLimit(1)
                                    Spacer()
                                    StatusPill(text: clip.provenance)
                                }
                                HStack(spacing: 12) {
                                    if let slug = clip.campaignSlug, !slug.isEmpty {
                                        Label(displayStatus(slug), systemImage: "rectangle.3.group")
                                    }
                                    Label(clip.sourcePlatform, systemImage: "play.tv")
                                    Text(String(format: "%.1fs", clip.duration))
                                        .monospacedDigit()
                                    Text(clip.discoveredAt)
                                        .foregroundStyle(.secondary)
                                }
                                .font(.caption)
                                Text(shortText(clip.localMediaPath, limit: 120))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(2)
                                    .textSelection(.enabled)
                            }
                            .padding(14)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                    .padding(.horizontal, 22)
                    .padding(.bottom, 22)
                }
            }
        }
        .searchable(text: $searchText, placement: .toolbar, prompt: "Search clips")
    }
}
