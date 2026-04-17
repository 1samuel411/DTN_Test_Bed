import React, { ReactNode } from 'react';

interface PanelProps {
  title: string;
  subtitle?: string;
  children: ReactNode;
  className?: string;
  /** When true, section is marked busy for assistive tech (e.g. async actions in progress). */
  busy?: boolean;
}

export function Panel({ title, subtitle, children, className, busy }: PanelProps) {
  return (
    <section className={`panel ${className ?? ''}`.trim()} aria-busy={busy === true ? true : undefined}>
      <header className="panel-header">
        <div>
          {subtitle ? (
            <>
              <p className="panel-kicker">{title}</p>
              <h2 className="panel-title">{subtitle}</h2>
            </>
          ) : (
            <h2 className="panel-title">{title}</h2>
          )}
        </div>
      </header>
      {children}
    </section>
  );
}
