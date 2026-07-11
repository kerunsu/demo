const REPORT_BUBBLES = [52, 30, 66, 44, 78, 38, 58, 26];

export function ReportBackgroundBubbles() {
  return (
    <div className="report-bg-bubbles" aria-hidden="true">
      {REPORT_BUBBLES.map((size, index) => (
        <span
          key={`${size}-${index}`}
          className="report-bubble"
          style={
            {
              width: `${size}px`,
              height: `${size}px`,
              left: `${8 + index * 12}%`,
              animationDuration: `${5 + (index % 5)}s`,
              animationDelay: `${(index % 4) * 0.4}s`
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  );
}
