/** Marks the reference run for its test name; other runs are compared against it. */
export function BaselineTag() {
  return (
    <span className="tag" title="Reference run for this test name">
      Baseline
    </span>
  );
}
