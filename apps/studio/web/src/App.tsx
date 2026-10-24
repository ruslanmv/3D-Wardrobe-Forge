import clsx from 'clsx';
import { LayoutGrid, Shirt, Sparkles } from 'lucide-react';
import { useEffect, useState, useSyncExternalStore } from 'react';

import { Gallery } from '@/components/Gallery';
import { Inspector, type StudioMode } from '@/components/Inspector';
import { ViewerPanel } from '@/components/ViewerPanel';
import {
    api,
    type Capabilities,
    type Catalog,
    type CatalogGarment,
    type Library,
    type LibraryAvatar,
} from '@/lib/forge';

const WIDE = '(min-width: 1024px)';

function useMedia(query: string): boolean {
    return useSyncExternalStore(
        (notify) => {
            const list = window.matchMedia(query);
            list.addEventListener('change', notify);
            return () => list.removeEventListener('change', notify);
        },
        () => window.matchMedia(query).matches,
        () => true,
    );
}

type Loaded<T> = { data: T | null; error: string | null };

function useForge<T>(load: () => Promise<T>): Loaded<T> {
    const [state, setState] = useState<Loaded<T>>({ data: null, error: null });
    useEffect(() => {
        let live = true;
        load()
            .then((data) => live && setState({ data, error: null }))
            .catch((e: Error) => live && setState({ data: null, error: e.message }));
        return () => {
            live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- each loader runs once
    }, []);
    return state;
}

/**
 * UI-002. The next Studio: one application, three depths (Explore, Design, Inspect).
 *
 * Wide screens get gallery, viewer and inspector side by side. Narrow ones put the viewer first
 * and switch the panel under it with a bottom bar: the desktop's three columns are never squeezed
 * onto a phone, and only one layout — so one WebGL viewer — is ever mounted.
 */
export default function App() {
    const wide = useMedia(WIDE);
    const capabilities = useForge<Capabilities>(api.capabilities);
    const library = useForge<Library>(api.library);
    const catalog = useForge<Catalog>(() => api.catalogGarments());
    const [avatarSlug, setAvatarSlug] = useState<string | null>(null);
    const [garment, setGarment] = useState<CatalogGarment | null>(null);
    const [mode, setMode] = useState<StudioMode>('explore');
    const [panel, setPanel] = useState<'gallery' | 'garment'>('gallery');

    const avatars = (library.data?.avatars ?? []).filter((a) => a.available);
    const avatar: LibraryAvatar | null = avatars.find((a) => a.slug === avatarSlug) ?? avatars[0] ?? null;
    const keyRequired = Boolean(capabilities.data?.auth.keyRequired);
    const failure = capabilities.error || library.error || catalog.error;

    const choose = (g: CatalogGarment) => {
        setGarment(g);
        if (!wide) setPanel('garment');
    };

    const gallery = (
        <Gallery catalog={catalog.data} keyRequired={keyRequired} selected={garment?.id ?? null} onSelect={choose} />
    );
    const inspector = <Inspector garment={garment} mode={mode} onModeChange={setMode} />;

    return (
        <div className="flex h-dvh flex-col overflow-hidden">
            <header className="flex items-center gap-3 border-b border-line bg-surface px-3 py-2">
                <span className="flex items-center gap-2 font-semibold">
                    <Sparkles size={18} className="text-accent" aria-hidden />
                    Wardrobe Studio
                </span>
                <span className="rounded-full bg-raised px-2 py-0.5 text-xs text-muted">preview</span>
                <label className="ml-auto flex items-center gap-2 text-sm">
                    <span className="text-muted max-sm:sr-only">Avatar</span>
                    <select
                        value={avatar?.slug ?? ''}
                        onChange={(e) => setAvatarSlug(e.target.value)}
                        className="h-9 max-w-[11rem] rounded-lg border border-line bg-surface px-2 text-sm pointer-coarse:min-h-11"
                        disabled={!avatars.length}
                    >
                        {avatars.map((a) => (
                            <option key={a.slug} value={a.slug}>
                                {a.name}
                            </option>
                        ))}
                    </select>
                </label>
            </header>

            {failure && (
                <p role="alert" className="border-b border-line bg-raised px-3 py-2 text-sm text-bad">
                    Forge did not answer: {failure}
                </p>
            )}

            {wide ? (
                <main className="grid min-h-0 flex-1 grid-cols-[minmax(17rem,22rem)_1fr_minmax(19rem,24rem)]">
                    <div className="min-h-0 border-r border-line bg-surface">{gallery}</div>
                    <div className="min-h-0">
                        <ViewerPanel avatar={avatar} />
                    </div>
                    <div className="min-h-0 border-l border-line bg-surface">{inspector}</div>
                </main>
            ) : (
                <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <div className="h-[46svh] min-h-[15rem] shrink-0">
                        <ViewerPanel avatar={avatar} compact />
                    </div>
                    <div className="min-h-0 flex-1 overflow-hidden bg-surface">
                        {panel === 'gallery' ? gallery : inspector}
                    </div>
                    <nav
                        aria-label="Studio sections"
                        className="grid grid-cols-2 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]"
                    >
                        {(
                            [
                                ['gallery', 'Gallery', <LayoutGrid key="g" size={18} aria-hidden />],
                                ['garment', 'Garment', <Shirt key="s" size={18} aria-hidden />],
                            ] as const
                        ).map(([id, label, icon]) => (
                            <button
                                key={id}
                                type="button"
                                aria-current={panel === id ? 'page' : undefined}
                                onClick={() => setPanel(id)}
                                className={clsx(
                                    'flex min-h-12 flex-col items-center justify-center gap-0.5 text-xs',
                                    panel === id ? 'text-accent' : 'text-muted',
                                )}
                            >
                                {icon}
                                {label}
                            </button>
                        ))}
                    </nav>
                </main>
            )}

            {wide && (
                <footer
                    className="flex items-center gap-3 border-t border-line bg-surface px-3 py-1.5 text-xs text-muted"
                    aria-live="polite"
                >
                    <span>{avatar ? `${avatar.name} · ${avatar.license}` : 'No avatar'}</span>
                    <span aria-hidden>·</span>
                    <span>{garment ? `${garment.name} selected` : 'No garment selected'}</span>
                    <span className="ml-auto">No look generated in this Studio yet</span>
                </footer>
            )}
        </div>
    );
}
