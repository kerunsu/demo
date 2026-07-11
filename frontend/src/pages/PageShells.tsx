import type { ReactNode } from "react";
import type { CourseType } from "../types";

type PageShellProps = {
  transition: "active" | "hidden";
  children: ReactNode;
};

export function WelcomePageShell({ transition, children }: PageShellProps) {
  return <section className={`home-screen view-section-react ${transition}`}>{children}</section>;
}

export function CourseSelectPageShell({ transition, children }: PageShellProps) {
  return <section className={`course-select-screen view-section-react ${transition}`}>{children}</section>;
}

export function TrainingPageShell({
  transition,
  courseType,
  flashBg,
  children
}: PageShellProps & { courseType: CourseType; flashBg: boolean }) {
  return (
    <section className={`immersive-panel-fun view-section-react ${transition} ${courseType}-mode ${flashBg ? "flash-bg" : ""}`}>
      {children}
    </section>
  );
}

export function ReportPageShell({ transition, children }: PageShellProps) {
  return <section className={`report-screen view-section-react ${transition}`}>{children}</section>;
}

export function ReportDetailPageShell({
  transition,
  layout,
  children
}: PageShellProps & { layout: "landscape" | "portrait" }) {
  return (
    <section className={`report-detail-page view-section-react ${transition} ${layout === "landscape" ? "report-detail-page-landscape" : ""}`}>
      {children}
    </section>
  );
}
