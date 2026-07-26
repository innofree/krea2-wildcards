# Invalid style-template trial v0.5

Status: quarantined; excluded from scoring and lifecycle transitions.

The first 20 completed 1024 × 1024 runs used a style-pack benchmark that did not fix subject
count, pose, camera, wardrobe, background, or lighting. Early visual inspection found clear style
response, but the prompt produced multiple subjects and cropped or absent faces. Those images
cannot support the Phase 6 single-axis comparison or the character-quality metric.

The batch was stopped without cancelling any remote job. Every in-flight run completed, all 20
PNG files decode at the expected dimensions, stored metadata uses only `private_comfyui`, and the
remote queue was empty after shutdown. The replacement benchmark fixes one adult subject and all
complementary axes. Valid evaluation restarts in a new report directory; these runs are retained
only as process evidence and must never be merged into a scorecard.
