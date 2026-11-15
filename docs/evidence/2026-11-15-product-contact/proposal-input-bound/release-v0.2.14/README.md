# Released review-input bound

The v0.2.14 tag resolves to0781dbd9ba42d3f106a96cbd0502a5cb4b3a5574. Two clean exact-tag offline wheel builds are byte-identical. All62 runtime files match the tag. The three published assets were downloaded and compared byte-for-byte; the downloaded wheel is installed externally as0.2.14, and all62 installed runtime files and all three input/output bounds match.

Release: https://github.com/bayleafwalker/lanectl/releases/tag/v0.2.14
Wheel SHA256:8d5f716d92a18d4ecc8497a76ce98e4548d26b101925c8ed0e9d711739a8fa38 (225976bytes).

The initial sandboxed build failed at the uv cache lock before building. Its output is retained; the two successful clean contexts were built with the required host execution permission. Cached build-tool reproducibility is the scope of this observation.

The official large-input native review remains pending. LANECTL2906/res506 remains active. HLA1587 R2 is not accepted: independent review found the native-browser dependency in its Docker fallback and the missing actual stale-row precondition. R3 repair is independent product acceptance work, with no implementation attempt consumed.

Pushed Git is cross-host-replicated; served tracker state is durable-authoritative. Original/tmp wheel/build contexts are host-local scratch.
