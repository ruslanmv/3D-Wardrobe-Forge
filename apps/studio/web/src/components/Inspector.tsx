import * as Tabs from '@radix-ui/react-tabs';
import { ExternalLink, Info } from 'lucide-react';

import type { CatalogGarment, LibraryAvatar } from '@/lib/forge';
import { DesignPanel } from './design/DesignPanel';

export type StudioMode = 'explore' | 'design' | 'inspect';

const MODES: { id: StudioMode; label: string; hint: string }[] = [
    { id: 'explore', label: 'Explore', hint: 'Style, colour and material' },
    { id: 'design', label: 'Design', hint: 'Construction and measurements' },
    { id: 'inspect', label: 'Inspect', hint: 'Provenance and raw values' },
];

/**
 * UI-005 (first part). One inspector, three depths: Explore, Design, Inspect.
 *
 * It shows only what Forge actually says about the garment. Design's controls come from the
 * garment's parameter schema (UI-006, DesignPanel): each is a request field Forge reads, and
 * the construction a request cannot change is shown, never offered.
 */
export function Inspector({
    garment,
    avatar,
    mode,
    onModeChange,
}: {
    garment: CatalogGarment | null;
    avatar: LibraryAvatar | null;
    mode: StudioMode;
    onModeChange: (mode: StudioMode) => void;
}) {
    return (
        <section aria-labelledby="inspector-heading" className="flex h-full min-h-0 flex-col">
            <h2 id="inspector-heading" className="sr-only">
                Garment inspector
            </h2>
            <Tabs.Root
                value={mode}
                onValueChange={(v) => onModeChange(v as StudioMode)}
                className="flex min-h-0 flex-1 flex-col"
            >
                <Tabs.List aria-label="Inspector depth" className="grid grid-cols-3 gap-1 border-b border-line p-2">
                    {MODES.map((m) => (
                        <Tabs.Trigger
                            key={m.id}
                            value={m.id}
                            title={m.hint}
                            className="rounded-lg px-2 py-1.5 text-sm font-medium text-muted data-[state=active]:bg-raised data-[state=active]:text-ink pointer-coarse:min-h-11"
                        >
                            {m.label}
                        </Tabs.Trigger>
                    ))}
                </Tabs.List>

                <Tabs.Content value="explore" className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
                    {!garment ? (
                        <Empty />
                    ) : (
                        <>
                            <header>
                                <h3 className="text-lg font-semibold">{garment.name}</h3>
                                <p className="mt-1 text-sm text-muted">{garment.description}</p>
                            </header>
                            <Facts
                                rows={[
                                    ['Category', garment.category],
                                    ['Silhouette', garment.silhouette],
                                    ['Hem', garment.hem],
                                    ['Sleeve', garment.sleeve],
                                ]}
                            />
                            <div>
                                <h4 className="mb-1.5 text-sm font-semibold">Colours</h4>
                                {garment.supportsColor && garment.availableColors.length ? (
                                    <ul className="flex flex-wrap gap-1.5" aria-label="Available colours">
                                        {garment.availableColors.map((c) => (
                                            <li
                                                key={c}
                                                className="flex items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-xs capitalize"
                                            >
                                                <span
                                                    className="size-3 rounded-full border border-line"
                                                    style={{ background: c }}
                                                    aria-hidden
                                                />
                                                {c}
                                            </li>
                                        ))}
                                    </ul>
                                ) : (
                                    <p className="text-sm text-muted">This garment's colour is fixed by its design.</p>
                                )}
                            </div>
                            <div>
                                <h4 className="mb-1.5 text-sm font-semibold">Materials</h4>
                                <p className="text-sm capitalize">
                                    {garment.supportedMaterials.join(', ') || 'As designed'}
                                </p>
                            </div>
                            <Note>
                                Generating a look is still done in the classic Studio while this one is built.{' '}
                                <a
                                    href="/studio/"
                                    className="inline-flex items-center gap-1 font-medium text-accent underline"
                                >
                                    Open the classic Studio <ExternalLink size={12} aria-hidden />
                                </a>
                            </Note>
                        </>
                    )}
                </Tabs.Content>

                <Tabs.Content value="design" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                    {!garment ? <Empty /> : <DesignPanel garment={garment} avatar={avatar} />}
                </Tabs.Content>

                <Tabs.Content value="inspect" className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
                    {!garment ? (
                        <Empty />
                    ) : (
                        <>
                            <h3 className="text-base font-semibold">As Forge reports it</h3>
                            <Facts
                                rows={[
                                    ['Template', garment.id],
                                    ['Preview', garment.previewStatus],
                                    ['Restricted', garment.requiresAdult ? 'yes (admin session)' : 'no'],
                                ]}
                            />
                            <pre
                                className="overflow-x-auto rounded-lg bg-raised p-3 text-xs"
                                aria-label="Catalogue record"
                            >
                                {JSON.stringify(garment, null, 2)}
                            </pre>
                        </>
                    )}
                </Tabs.Content>
            </Tabs.Root>
        </section>
    );
}

function Empty() {
    return <p className="text-sm text-muted">Choose a garment from the gallery to see what it is made of.</p>;
}

function Facts({ rows }: { rows: [string, string][] }) {
    return (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            {rows.map(([k, v]) => (
                <div key={k} className="contents">
                    <dt className="text-muted">{k}</dt>
                    <dd className="capitalize">{v || '—'}</dd>
                </div>
            ))}
        </dl>
    );
}

function Note({ children }: { children: React.ReactNode }) {
    return (
        <p className="flex gap-2 rounded-lg border border-line bg-raised p-3 text-sm text-muted">
            <Info size={16} className="mt-0.5 shrink-0" aria-hidden />
            <span>{children}</span>
        </p>
    );
}
