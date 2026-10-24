import clsx from 'clsx';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type Base = ButtonHTMLAttributes<HTMLButtonElement> & { icon?: ReactNode; children: ReactNode };

// Targets: 36 px with a mouse, 44 px on a touch screen (WCAG 2.5.8 asks 24; fingers want more).
const base =
    'inline-flex items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium h-9 pointer-coarse:min-h-11 ' +
    'transition-colors disabled:cursor-not-allowed disabled:opacity-45';

/** A button that is on or off: state is announced with aria-pressed, never shown by colour alone. */
export function ToggleButton({ pressed, icon, children, className, ...rest }: Base & { pressed: boolean }) {
    return (
        <button
            type="button"
            aria-pressed={pressed}
            className={clsx(base, pressed ? 'bg-accent text-accent-ink' : 'text-ink hover:bg-raised', className)}
            {...rest}
        >
            {icon && <span aria-hidden>{icon}</span>}
            {children}
        </button>
    );
}

export function ToolbarButton({ icon, children, className, ...rest }: Base) {
    return (
        <button type="button" className={clsx(base, 'text-ink hover:bg-raised', className)} {...rest}>
            {icon && <span aria-hidden>{icon}</span>}
            {children}
        </button>
    );
}

export function PrimaryButton({ icon, children, className, ...rest }: Base) {
    return (
        <button
            type="button"
            className={clsx(base, 'bg-accent px-4 text-accent-ink hover:opacity-90', className)}
            {...rest}
        >
            {icon && <span aria-hidden>{icon}</span>}
            {children}
        </button>
    );
}
