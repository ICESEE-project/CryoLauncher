"""Curated registry of CryoStack-tested container images.

A *tested image* is an OCI image whose entire software stack CryoStack has
validated end-to-end against one or more models. The registry lets the UI offer
a curated dropdown instead of asking a user to type an image reference by hand,
and feeds a verified digest into the run's container provenance.

The registry is intentionally generic — model support is a per-entry tuple — so
ISSM-only images, Icepack-only images, newer tested stacks, GPU images and
cloud/ECR mirrors can be added later without any UI change.

Per-component version facts for the ICESEE combined image already live in
:mod:`cryostack_src.models.stack.components` (they are the image's *baked*
identity, resolved into every run's manifest ``software`` block). The
``components`` mapping here only carries extra, image-specific provenance that
the component registry does not already record — it is never a second source of
truth for a component's baked version.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TestedImage:
    key: str
    label: str
    reference: str                  # OCI reference (a Docker Hub tag today)
    digest: str                     # "sha256:..." verified against the registry
    models: tuple[str, ...]         # CryoStack models this image supports
    stack_profile: str = "tested"
    components: dict = field(default_factory=dict)

    def supports(self, model: str) -> bool:
        return (model or "").strip().lower() in self.models

    @property
    def docker_reference(self) -> str:
        """The reference with an explicit ``docker://`` transport."""
        return self.reference if "://" in self.reference else f"docker://{self.reference}"

    @property
    def short_digest(self) -> str:
        return f"{self.digest[:15]}…" if self.digest.startswith("sha256:") else self.digest

    @property
    def public_url(self) -> str | None:
        """A navigable page for this image on its public registry (Docker Hub
        today), or ``None`` when the reference is not a recognisable Docker
        Hub ``[docker.io/]<namespace>/<repo>[:<tag>]`` reference. Used to give
        the Review / CLOUD RUN cards a link straight to the exact image."""
        ref = self.reference.split("://", 1)[-1].split("@", 1)[0]
        repo, _, tag = ref.partition(":")
        parts = repo.split("/")
        if parts and parts[0] in ("docker.io", "index.docker.io",
                                  "registry-1.docker.io"):
            parts = parts[1:]
        if len(parts) != 2 or not all(parts):
            return None
        namespace, name = parts
        base = f"https://hub.docker.com/r/{namespace}/{name}"
        return f"{base}/tags?name={tag}" if tag else f"{base}/tags"


# ── the registry ────────────────────────────────────────────────────────────
# Insertion order matters: default_tested_image_for_model() returns the FIRST
# entry that supports a model, so the current default goes first. Superseded
# entries are kept, never deleted or overwritten -- an already-mirrored ECR
# image (or a run's recorded provenance) must always resolve back to a real,
# unmodified registry fact, even after a newer tested image is added.
TESTED_IMAGES: dict[str, TestedImage] = {
    "icesee-combined-v1.0.1": TestedImage(
        key="icesee-combined-v1.0.1",
        label="ICESEE Combined v1.0.1",
        reference="bkyanjo/icesee-combined:v1.0.1",
        digest="sha256:e393b1eed21f3481fffcfb3bb7ce5ce315fbff0cc8dc0fe4f2bcc2e2f1d538ed",
        models=("issm", "icepack"),
        components={
            # unchanged from v1.0.0 -- this release ONLY adds the AWS CLI
            # (cloud S3 input/output sync); no scientific-stack layer was
            # rebuilt (confirmed: the pip/ICESEE dependency layer built
            # byte-identical / cache-hit against v1.0.0's own build).
            "issm": {
                "version": "2026.1 (self-reported)",
                "commit": "e70338d8685f8582b61958211e8f5fce2ea686ff",
            },
            "firedrake": {"version": "2025.10.2"},
        },
    ),
    "icesee-combined-v1.0.0": TestedImage(
        key="icesee-combined-v1.0.0",
        label="ICESEE Combined v1.0.0",
        reference="bkyanjo/icesee-combined:v1.0.0",
        digest="sha256:a727f60a738c748d1812b157e1fe94ddb1177ecc32354afa7b747db2f6b7bae5",
        models=("issm", "icepack"),
        components={
            # mirrors cryostack_src.models.stack.components — kept only so a
            # future image whose baked stack differs from the current registry
            # can state its own facts here.
            "issm": {
                "version": "2026.1 (self-reported)",
                "commit": "e70338d8685f8582b61958211e8f5fce2ea686ff",
            },
            "firedrake": {"version": "2025.10.2"},
        },
    ),
}


def all_tested_images() -> tuple[TestedImage, ...]:
    return tuple(TESTED_IMAGES.values())


def get_tested_image(key: str) -> TestedImage:
    try:
        return TESTED_IMAGES[key]
    except KeyError:
        raise KeyError(f"Unknown tested image: {key!r}") from None


def tested_images_for_model(model: str) -> tuple[TestedImage, ...]:
    m = (model or "").strip().lower()
    return tuple(img for img in TESTED_IMAGES.values() if m in img.models)


def default_tested_image_for_model(model: str) -> TestedImage | None:
    imgs = tested_images_for_model(model)
    return imgs[0] if imgs else None


def find_tested_image(reference_or_key: str) -> TestedImage | None:
    """Best-effort lookup of a tested image by registry key or OCI reference.

    Used to attach registry provenance when a *custom* reference the user typed
    happens to be a tested image. A tag-only match is intentionally loose; the
    digest is only trusted when it is the registry's own.
    """
    token = (reference_or_key or "").strip()
    if not token:
        return None
    if token in TESTED_IMAGES:
        return TESTED_IMAGES[token]
    norm = token.split("://", 1)[-1].split("@", 1)[0]
    for img in TESTED_IMAGES.values():
        if img.reference == token or img.reference.split("@", 1)[0] == norm:
            return img
    return None
