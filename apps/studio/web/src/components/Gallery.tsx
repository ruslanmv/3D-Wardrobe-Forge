import * as Tabs from '@radix-ui/react-tabs';
import clsx from 'clsx';
import { ImageOff, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { filterGarments, type GalleryFilter } from '@/lib/catalog';
import { api, type Catalog, type CatalogGarment } from '@/lib/forge';

/**
 * UI-004. The garment gallery: the server's catalogue, its pre-rendered previews, nothing else.
 *
 * A catalogue GET never generates a garment (apps/api/routes/catalog.py), and this asks only for
 * the public catalogue: restricted pieces are listed by the server only to an admin session, and
 * this gallery does not ask until the Adult Studio flow exists. A piece with no rendered preview
 * says so; it is never shown a stand-in picture.
 */
export function Gallery({
    catalog,
    keyRequired,
    selected,
    onSelect,
}: {
    catalog: Catalog | null;
    keyRequired: boolean;
    selected: string | null;
    onSelect: (garment: CatalogGarment) => void;
}) {
    const [filter, setFilter] = useState<GalleryFilter>({ query: '', category: 'all', previewedOnly: false });
    const shown = useMemo(() => filterGarments(catalog, filter), [catalog, filter]);
    const categories = catalog?.categories ?? [];

    return (
        <section aria-labelledby="gallery-heading" className="flex h-full min-h-0 flex-col">
            <div className="space-y-2 border-b border-line p-3">
                <h2 id="gallery-heading" className="text-base font-semibold">
                    Garments
                </h2>
                <label className="relative block">
                    <span className="sr-only">Search garments</span>
                    <Search
                        className="pointer-events-none absolute top-2.5 left-2.5 text-muted"
                        size={16}
                        aria-hidden
                    />
                    <input
                        type="search"
                        value={filter.query}
                        onChange={(e) => setFilter({ ...filter, query: e.target.value })}
                        placeholder="Search: lace, mini, cropped…"
                        className="h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-8 text-sm pointer-coarse:min-h-11"
                    />
                </label>
                <label className="flex items-center gap-2 text-sm text-muted">
                    <input
                        type="checkbox"
                        checked={filter.previewedOnly}
                        onChange={(e) => setFilter({ ...filter, previewedOnly: e.target.checked })}
                        className="size-4 accent-[var(--color-accent)]"
                    />
                    With a rendered preview only
                </label>
            </div>

            <Tabs.Root
                value={filter.category}
                onValueChange={(category) => setFilter({ ...filter, category })}
                className="flex min-h-0 flex-1 flex-col"
            >
                <Tabs.List
                    aria-label="Garment category"
                    className="flex gap-1 overflow-x-auto border-b border-line px-2 py-1.5"
                >
                    {[{ id: 'all', label: 'All', count: catalog?.visibleCount ?? 0 }, ...categories].map((c) => (
                        <Tabs.Trigger
                            key={c.id}
                            value={c.id}
                            className="shrink-0 rounded-full px-3 py-1 text-sm text-muted data-[state=active]:bg-accent data-[state=active]:text-accent-ink pointer-coarse:min-h-11"
                        >
                            {c.label} <span>{c.count}</span>
                        </Tabs.Trigger>
                    ))}
                </Tabs.List>
                <Tabs.Content value={filter.category} className="min-h-0 flex-1 overflow-y-auto p-3" tabIndex={-1}>
                    <p className="mb-2 text-xs text-muted" aria-live="polite">
                        {catalog ? `${shown.length} of ${catalog.visibleCount} garments` : 'Loading the catalogue…'}
                    </p>
                    <ul className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-3">
                        {shown.map((garment) => (
                            <li key={garment.id}>
                                <GarmentCard
                                    garment={garment}
                                    keyRequired={keyRequired}
                                    selected={selected === garment.id}
                                    onSelect={onSelect}
                                />
                            </li>
                        ))}
                    </ul>
                </Tabs.Content>
            </Tabs.Root>
        </section>
    );
}

function GarmentCard({
    garment,
    keyRequired,
    selected,
    onSelect,
}: {
    garment: CatalogGarment;
    keyRequired: boolean;
    selected: boolean;
    onSelect: (garment: CatalogGarment) => void;
}) {
    return (
        <button
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(garment)}
            className={clsx(
                'group flex w-full flex-col overflow-hidden rounded-[var(--radius-card)] border bg-surface text-left',
                selected ? 'border-accent ring-2 ring-accent' : 'border-line hover:border-muted',
            )}
        >
            <div className="aspect-[3/4] w-full bg-raised">
                <Preview garment={garment} keyRequired={keyRequired} />
            </div>
            <span className="block px-2.5 pt-2 text-sm font-medium leading-snug">{garment.name}</span>
            <span className="block px-2.5 pb-2.5 text-xs text-muted capitalize">{garment.category}</span>
        </button>
    );
}

function Preview({ garment, keyRequired }: { garment: CatalogGarment; keyRequired: boolean }) {
    const [src, setSrc] = useState<string | null>(keyRequired ? null : garment.previewUrl);
    useEffect(() => {
        // A keyed deployment: an <img> cannot send the Authorization header, so fetch it.
        if (!keyRequired || !garment.previewUrl) return;
        let url: string | null = null;
        let live = true;
        api.blobUrl(garment.previewUrl).then((u) => (live ? setSrc((url = u)) : URL.revokeObjectURL(u)));
        return () => {
            live = false;
            if (url) URL.revokeObjectURL(url);
        };
    }, [garment.previewUrl, keyRequired]);

    if (!garment.previewUrl) {
        return (
            <span className="flex h-full flex-col items-center justify-center gap-1 p-2 text-center text-xs text-muted">
                <ImageOff size={18} aria-hidden />
                Preview not rendered yet
            </span>
        );
    }
    return src ? (
        <img
            src={src}
            alt={`${garment.name}, catalogue preview`}
            loading="lazy"
            decoding="async"
            className="h-full w-full object-cover"
        />
    ) : null;
}
