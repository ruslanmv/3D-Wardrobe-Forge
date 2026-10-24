import * as Slider from '@radix-ui/react-slider';
import * as ToggleGroup from '@radix-ui/react-toggle-group';
import clsx from 'clsx';
import { Lock, RotateCcw } from 'lucide-react';
import { useId } from 'react';

import { gated } from '@/lib/design';
import type { AdjustableChoice, AdjustableNumber, ReadOnlyParameter } from '@/lib/forge';

const SOURCE_LABEL: Record<string, string> = {
    template: 'designer',
    preset: 'preset',
    default: 'default',
    reference: 'drafted on her body',
    'template material policy': 'material policy',
};

function Header({ label, modified, onReset }: { label: string; modified: boolean; onReset: () => void }) {
    return (
        <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
                {label}
                {modified && (
                    <span className="ml-1.5 rounded bg-raised px-1.5 py-0.5 text-[11px] text-muted">changed</span>
                )}
            </span>
            {modified && (
                <button
                    type="button"
                    onClick={onReset}
                    className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted hover:bg-raised pointer-coarse:min-h-11"
                >
                    <RotateCcw size={12} aria-hidden /> Reset <span className="sr-only">{label}</span>
                </button>
            )}
        </div>
    );
}

/** A named choice: one button per value, each labelled in words (never only a swatch). */
export function ChoiceField({
    parameter,
    value,
    adultDeclared,
    onChange,
}: {
    parameter: AdjustableChoice;
    value: string | undefined;
    adultDeclared: boolean;
    onChange: (value: string | undefined) => void;
}) {
    const current = value ?? parameter.default ?? '';
    const labelId = useId();
    return (
        <div className="space-y-1.5">
            <div id={labelId}>
                <Header label={parameter.label} modified={value !== undefined} onReset={() => onChange(undefined)} />
            </div>
            <ToggleGroup.Root
                type="single"
                value={current}
                onValueChange={(next) => next && onChange(next === parameter.default ? undefined : next)}
                aria-labelledby={labelId}
                className="flex flex-wrap gap-1.5"
            >
                {parameter.options.map((option) => {
                    const locked = !adultDeclared && gated(parameter, option.value);
                    return (
                        <ToggleGroup.Item
                            key={option.value}
                            value={option.value}
                            disabled={locked}
                            title={locked ? 'See-through: needs the avatar declared adult' : undefined}
                            className={clsx(
                                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs capitalize pointer-coarse:min-h-11',
                                'data-[state=on]:border-accent data-[state=on]:bg-accent data-[state=on]:text-accent-ink',
                                'border-line disabled:cursor-not-allowed disabled:opacity-45',
                            )}
                        >
                            {option.hex && (
                                <span
                                    className="size-3 rounded-full border border-line"
                                    style={{ background: option.hex }}
                                    aria-hidden
                                />
                            )}
                            {option.label}
                            {locked && <Lock size={11} aria-label="needs adult declaration" />}
                        </ToggleGroup.Item>
                    );
                })}
            </ToggleGroup.Root>
            {parameter.default === null && value === undefined && (
                <p className="text-xs text-muted">Unset: Forge chooses.</p>
            )}
        </div>
    );
}

/** A number: typed exactly, or slid; its unit always shown; the gate explained, never hidden. */
export function NumberField({
    parameter,
    value,
    adultDeclared,
    onChange,
}: {
    parameter: AdjustableNumber;
    value: number | undefined;
    adultDeclared: boolean;
    onChange: (value: number | undefined) => void;
}) {
    const inputId = useId();
    const floor =
        !adultDeclared && parameter.requiresAdultDeclarationBelow !== undefined
            ? parameter.requiresAdultDeclarationBelow
            : parameter.min;
    const current = value ?? parameter.default;
    const set = (next: number) => {
        if (Number.isNaN(next)) return;
        const clamped = Math.min(parameter.max, Math.max(floor, next));
        onChange(clamped === parameter.default ? undefined : Number(clamped.toFixed(3)));
    };
    const locked = floor >= parameter.max;
    return (
        <div className="space-y-1.5">
            <Header label={parameter.label} modified={value !== undefined} onReset={() => onChange(undefined)} />
            <div className="flex items-center gap-3">
                <Slider.Root
                    value={[current]}
                    min={parameter.min}
                    max={parameter.max}
                    step={parameter.step}
                    disabled={locked}
                    onValueChange={([next]) => set(next)}
                    className="relative flex h-5 flex-1 touch-none items-center select-none data-[disabled]:opacity-45"
                >
                    <Slider.Track className="relative h-1 flex-1 rounded-full bg-line">
                        <Slider.Range className="absolute h-full rounded-full bg-accent" />
                    </Slider.Track>
                    <Slider.Thumb
                        aria-label={`${parameter.label}, ${parameter.unit}`}
                        className="block size-4 rounded-full border-2 border-accent bg-surface"
                    />
                </Slider.Root>
                <label htmlFor={inputId} className="sr-only">
                    {parameter.label} ({parameter.unit})
                </label>
                <input
                    id={inputId}
                    type="number"
                    inputMode="decimal"
                    min={floor}
                    max={parameter.max}
                    step={parameter.step}
                    value={current}
                    disabled={locked}
                    onChange={(e) => set(e.target.valueAsNumber)}
                    className="h-8 w-20 rounded-md border border-line bg-surface px-2 text-right text-sm tabular-nums pointer-coarse:min-h-11"
                />
            </div>
            <p className="text-xs text-muted">
                {parameter.unit}. {parameter.description}
                {locked && ' See-through needs the avatar declared adult, so this stays at 1.'}
            </p>
        </div>
    );
}

/** Construction the request cannot change: value, unit, and who decided it. */
export function ReadOnlyTable({ parameters }: { parameters: ReadOnlyParameter[] }) {
    return (
        <dl className="divide-y divide-line rounded-lg border border-line text-sm">
            {parameters.map((p) => (
                <div key={p.id} className="grid grid-cols-[1fr_auto] gap-x-3 px-3 py-2" title={p.description}>
                    <dt className="text-muted">{p.label}</dt>
                    <dd className="text-right tabular-nums">
                        {p.value === null ? '—' : String(p.value)}
                        {p.unit !== 'word' && p.unit !== 'boolean' && p.value !== null && (
                            <span className="ml-1 text-xs text-muted">{p.unit}</span>
                        )}
                    </dd>
                    <dd className="col-span-2 text-[11px] text-muted">
                        {SOURCE_LABEL[p.source] ?? p.source}
                        {p.source === 'reference' && ': no single value until a body is chosen'}
                    </dd>
                </div>
            ))}
        </dl>
    );
}
