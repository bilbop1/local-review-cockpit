import AppKit
import AVKit
import SwiftUI

@MainActor
final class ReviewVideoPlaybackController: ObservableObject {
    @Published var isPlaying = false
    @Published var isMuted = false
    @Published var currentTime = 0.0
    @Published var duration = 0.0

    private weak var player: AVPlayer?
    private weak var observedPlayer: AVPlayer?
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var userPaused = false

    var progressRange: ClosedRange<Double> {
        0...max(duration, 1.0)
    }

    func attach(_ player: AVPlayer) {
        detach()
        self.player = player
        observedPlayer = player
        player.isMuted = isMuted
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime,
            object: player.currentItem,
            queue: .main
        ) { [weak self, weak player] _ in
            Task { @MainActor in
                guard let self, let player else { return }
                self.sync(from: player)
                self.isPlaying = false
            }
        }
        timeObserver = player.addPeriodicTimeObserver(
            forInterval: CMTime(seconds: 0.2, preferredTimescale: 600),
            queue: .main
        ) { [weak self, weak player] _ in
            Task { @MainActor in
                guard let self, let player else { return }
                self.sync(from: player)
            }
        }
        sync(from: player)
        if userPaused {
            isPlaying = false
        } else if player.timeControlStatus == .playing || player.timeControlStatus == .waitingToPlayAtSpecifiedRate || player.rate > 0 {
            isPlaying = true
        }
    }

    func detach() {
        detach(matching: nil)
    }

    func prepareForAutoplay() {
        userPaused = false
    }

    var shouldAutoplay: Bool {
        !userPaused
    }

    func detach(matching targetPlayer: AVPlayer?) {
        if let targetPlayer, player !== targetPlayer, observedPlayer !== targetPlayer {
            return
        }
        if let timeObserver, let observedPlayer {
            observedPlayer.removeTimeObserver(timeObserver)
        }
        if let endObserver {
            NotificationCenter.default.removeObserver(endObserver)
        }
        timeObserver = nil
        endObserver = nil
        player = nil
        observedPlayer = nil
        userPaused = false
        isPlaying = false
        currentTime = 0.0
        duration = 0.0
    }

    func togglePlayback() {
        guard let player else { return }
        if player.timeControlStatus == .playing || player.rate > 0 || isPlaying {
            userPaused = true
            player.pause()
            isPlaying = false
        } else {
            userPaused = false
            if duration > 0, currentTime >= duration - 0.15 {
                player.seek(to: CMTime(seconds: 0.0, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
            }
            player.playImmediately(atRate: 1.0)
            isPlaying = true
        }
        sync(from: player)
    }

    func restart() {
        guard let player else { return }
        userPaused = false
        currentTime = 0.0
        isPlaying = true
        player.seek(to: CMTime(seconds: 0.0, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) { [weak self, weak player] _ in
            Task { @MainActor in
                guard let self, let player else { return }
                player.playImmediately(atRate: 1.0)
                self.sync(from: player)
                self.isPlaying = true
            }
        }
    }

    func seek(to seconds: Double) {
        guard let player else { return }
        let clamped = max(0, min(seconds, max(duration, 0)))
        currentTime = clamped
        player.seek(
            to: CMTime(seconds: clamped, preferredTimescale: 600),
            toleranceBefore: .zero,
            toleranceAfter: .zero
        ) { [weak self, weak player] _ in
            Task { @MainActor in
                guard let self, let player else { return }
                self.sync(from: player)
            }
        }
    }

    func skip(_ delta: Double) {
        seek(to: currentTime + delta)
    }

    func toggleMuted() {
        isMuted.toggle()
        player?.isMuted = isMuted
    }

    func refresh() {
        guard let player else { return }
        sync(from: player)
    }

    func markPlaying() {
        isPlaying = true
    }

    private func sync(from player: AVPlayer) {
        let current = player.currentTime().seconds
        if current.isFinite {
            currentTime = current
        }
        let itemDuration = player.currentItem?.duration.seconds ?? 0
        if itemDuration.isFinite && itemDuration > 0 {
            duration = itemDuration
        }
        isPlaying = player.timeControlStatus == .playing || player.timeControlStatus == .waitingToPlayAtSpecifiedRate || player.rate > 0
        isMuted = player.isMuted
    }
}

struct CrashSafeVideoPreview: NSViewRepresentable {
    var url: URL
    @Binding var isReady: Bool
    var playback: ReviewVideoPlaybackController

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSView {
        let container = NSView()
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor.black.cgColor

        let playerView = AVPlayerView()
        playerView.translatesAutoresizingMaskIntoConstraints = false
        playerView.controlsStyle = .none
        playerView.videoGravity = .resizeAspect

        container.addSubview(playerView)
        NSLayoutConstraint.activate([
            playerView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            playerView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            playerView.topAnchor.constraint(equalTo: container.topAnchor),
            playerView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])
        context.coordinator.playerView = playerView
        return container
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.configure(url: url, playback: playback) {
            isReady = true
        }
    }

    static func dismantleNSView(_ nsView: NSView, coordinator: Coordinator) {
        Task { @MainActor in
            coordinator.stop()
        }
    }

    @MainActor
    final class Coordinator {
        weak var playerView: AVPlayerView?
        private var player: AVPlayer?
        private var currentURL: URL?
        private weak var playback: ReviewVideoPlaybackController?
        private var generation = 0
        private var itemStatusObserver: NSKeyValueObservation?
        private var autoplayTask: Task<Void, Never>?

        func configure(url: URL, playback: ReviewVideoPlaybackController, ready: @escaping @MainActor () -> Void) {
            self.playback = playback
            guard currentURL != url else {
                playback.refresh()
                ready()
                return
            }
            generation += 1
            let loadGeneration = generation
            stop()
            generation = loadGeneration
            currentURL = url
            let item = AVPlayerItem(url: url)
            let nextPlayer = AVPlayer(playerItem: item)
            nextPlayer.actionAtItemEnd = .pause
            nextPlayer.automaticallyWaitsToMinimizeStalling = false
            player = nextPlayer
            playerView?.player = nextPlayer
            playback.prepareForAutoplay()
            playback.attach(nextPlayer)
            itemStatusObserver = item.observe(\.status, options: [.initial, .new]) { [weak self, weak nextPlayer, weak playback] observedItem, _ in
                Task { @MainActor in
                    guard
                        let self,
                        let nextPlayer,
                        let playback,
                        self.generation == loadGeneration,
                        self.player === nextPlayer,
                        observedItem.status == .readyToPlay
                    else { return }
                    self.forceAutoplay(nextPlayer, playback: playback, generation: loadGeneration, ready: ready)
                }
            }
            nextPlayer.seek(
                to: CMTime(seconds: 0.15, preferredTimescale: 600),
                toleranceBefore: .zero,
                toleranceAfter: .zero
            ) { [weak self, weak nextPlayer] _ in
                Task { @MainActor in
                    guard let self, let nextPlayer, self.generation == loadGeneration, self.player === nextPlayer else { return }
                    self.forceAutoplay(nextPlayer, playback: playback, generation: loadGeneration, ready: ready)
                }
            }
        }

        private func forceAutoplay(
            _ targetPlayer: AVPlayer,
            playback: ReviewVideoPlaybackController,
            generation loadGeneration: Int,
            ready: @escaping @MainActor () -> Void
        ) {
            guard generation == loadGeneration, player === targetPlayer else { return }
            guard playback.shouldAutoplay else { return }
            targetPlayer.playImmediately(atRate: 1.0)
            playback.refresh()
            playback.markPlaying()
            ready()
            autoplayTask?.cancel()
            autoplayTask = Task { @MainActor in
                for _ in 0..<36 {
                    try? await Task.sleep(nanoseconds: 250_000_000)
                    guard !Task.isCancelled, self.generation == loadGeneration, self.player === targetPlayer else { return }
                    guard playback.shouldAutoplay else {
                        playback.refresh()
                        return
                    }
                    if targetPlayer.currentItem?.status == .readyToPlay,
                       targetPlayer.timeControlStatus != .playing,
                       targetPlayer.rate == 0 {
                        let current = targetPlayer.currentTime().seconds
                        let duration = targetPlayer.currentItem?.duration.seconds ?? 0
                        if duration.isFinite, duration > 0, current.isFinite, current >= duration - 0.15 {
                            targetPlayer.seek(to: CMTime(seconds: 0.15, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero) { [weak targetPlayer] _ in
                                Task { @MainActor in
                                    targetPlayer?.playImmediately(atRate: 1.0)
                                    playback.markPlaying()
                                }
                            }
                        } else {
                            targetPlayer.playImmediately(atRate: 1.0)
                            playback.markPlaying()
                        }
                    }
                    playback.refresh()
                    if playback.shouldAutoplay,
                       targetPlayer.timeControlStatus == .playing || targetPlayer.timeControlStatus == .waitingToPlayAtSpecifiedRate || targetPlayer.rate > 0 {
                        playback.markPlaying()
                    }
                }
            }
        }

        func stop() {
            generation += 1
            autoplayTask?.cancel()
            autoplayTask = nil
            itemStatusObserver?.invalidate()
            itemStatusObserver = nil
            let stoppedPlayer = player
            stoppedPlayer?.pause()
            stoppedPlayer?.replaceCurrentItem(with: nil)
            if playerView?.player === stoppedPlayer {
                playerView?.player = nil
            }
            player = nil
            currentURL = nil
            playback?.detach(matching: stoppedPlayer)
        }
    }
}
