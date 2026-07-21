# Asha World public game server — one-container world-sim + static export host.
#
# Build:  docker build -f games/asha_world/deploy/Dockerfile -t asha-world-server .
# Run:    docker run -p 8081:8081 -p 8080:8080 \
#            -e DATABASE_URL=postgres://user:pass@host:5432/studio \
#            asha-world-server
#
# Serves the WebGPU export with the COOP/COEP headers the threaded build needs
# (Static on :8080) and the world-sim WebSocket server (on :8081). Point the
# browser client at it with:  https://your-host/?ws=wss://your-host:8081

# --- build the game server ---
FROM rust:1.97-slim AS server-build
WORKDIR /src
COPY services/ services/
COPY games/asha_world/server/ games/asha_world/server/
RUN cargo build --release --manifest-path games/asha_world/server/Cargo.toml

# --- runtime ---
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=server-build /src/games/asha_world/server/target/release/asha_world-server /app/server
# Static export (built by `just export-browser-webgpu`) + the header-aware static server.
COPY games/asha_world/project/exports/web-webgpu/ /app/web/
COPY tools/godot/serve_web.py /app/serve_web.py

ENV STUDIO_DEDICATED_ADDR=0.0.0.0:8081 \
    STUDIO_LOG=info
EXPOSE 8080 8081

# Run both: the world-sim ws server and the static file server (with COOP/COEP).
COPY games/asha_world/deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
