FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder

ARG APP_DIR=/app
WORKDIR $APP_DIR

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=python3.13 \
    UV_PYTHON_INSTALL_DIR=/usr/share/uv/python

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev
COPY . $APP_DIR
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Then, use a final image without uv
FROM debian:bookworm-slim

ARG USERNAME=app
ARG USER_UID=1001
ARG USER_GID=118
ARG APP_DIR=/app
ARG WORKDIR=/app

ENV APP_DIR=$APP_DIR

EXPOSE 8000

LABEL maintainer="@" \
    org.opencontainers.image.authors="Corey Oordt coreyoordt@gmail.com" \
    org.opencontainers.image.created=2026-04-14T16:51:58Z \
    org.opencontainers.image.url="https://github.com/callowayproject/foreman" \
    org.opencontainers.image.source="https://github.com/callowayproject/foreman" \
    org.opencontainers.image.version="0.1.0" \
    org.opencontainers.image.licenses=MIT \
    org.opencontainers.image.documentation="https://github.com/callowayproject/foreman" \
    org.opencontainers.image.description="A Python harness that acts as an always-on AI co-maintainer for OSS repositories."

WORKDIR $WORKDIR

ENV PATH="$APP_DIR/.venv/bin:$PATH"

RUN groupadd --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME

RUN mkdir -p $WORKDIR \
  && chown $USERNAME:$USER_GID $WORKDIR

USER $USERNAME

COPY --from=builder --chown=$USERNAME:$USER_GID /usr/share/uv/python /usr/share/uv/python
COPY --from=builder --chown=$USERNAME:$USER_GID $APP_DIR $APP_DIR
CMD ["fastapi", "run", "foreman/main.py", "--port", "8000"]
