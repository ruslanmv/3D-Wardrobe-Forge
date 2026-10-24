import { Box, Columns2, Crosshair, Footprints, PersonStanding, RotateCw, Shirt } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { InspectView, Pose, Viewer, ViewMode } from '../../../js/viewer.js';
import { api, type LibraryAvatar } from '@/lib/forge';
import { ToggleButton, ToolbarButton } from './ui/buttons';

const VIEWS: { id: InspectView; label: string }[] = [
    { id: 'front', label: 'Front' },
    { id: 'side', label: 'Side' },
    { id: 'back', label: 'Back' },
    { id: 'free', label: 'Free' },
];

const prefersReducedMotion = () =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * UI-003. The existing Studio viewer (apps/studio/js/viewer.js), mounted as it is.
 *
 * It is not rewritten: Original / Look / Compare, relaxed and rest poses, Front / Side / Back /
 * Free, the touch gestures (one finger turns, a pinch zooms, two fingers pan, a double tap
 * resets) and the pose-space correctives all come with it. This component only owns its life
 * (created on mount, disposed on unmount), loads the chosen avatar through the API client (so a
 * keyed deployment's Authorization header goes with it), and gives every drag action a button.
 */
export function ViewerPanel({ avatar, compact = false }: { avatar: LibraryAvatar | null; compact?: boolean }) {
    const host = useRef<HTMLDivElement>(null);
    const viewer = useRef<Viewer | null>(null);
    const [ready, setReady] = useState(false);
    // Which avatar last landed, or failed: the status is derived from them, never set in an effect.
    const [landed, setLanded] = useState<string | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [mode, setMode] = useState<ViewMode>('original');
    const [view, setView] = useState<InspectView>('free');
    const [pose, setPose] = useState<Pose>('relaxed');
    const [turntable, setTurntable] = useState(false);

    // One viewer per mount; the 3D stack arrives as its own chunk.
    useEffect(() => {
        let disposed = false;
        let created: Viewer | null = null;
        import('../../../js/viewer.js').then(({ Viewer }) => {
            if (disposed || !host.current) return;
            created = new Viewer(host.current);
            viewer.current = created;
            setReady(true);
        });
        return () => {
            disposed = true;
            created?.dispose();
            viewer.current = null;
            setReady(false);
        };
    }, []);

    // Load the chosen avatar into the original slot; a later choice supersedes an earlier one.
    useEffect(() => {
        const v = viewer.current;
        if (!ready || !v) return;
        if (!avatar) {
            v.clear('original');
            return;
        }
        let url: string | null = null;
        let cancelled = false;
        api.blobUrl(avatar.fileUrl)
            .then((objectUrl) => {
                url = objectUrl;
                return cancelled ? false : v.load('original', objectUrl);
            })
            .then((done) => {
                if (cancelled || !done) return;
                v.setMode('original');
                v.frame();
                setMode('original');
                setLanded(avatar.slug);
            })
            .catch(() => !cancelled && setFailed(avatar.slug))
            .finally(() => url && URL.revokeObjectURL(url)); // the loader has read it: let it go
        return () => {
            cancelled = true;
        };
    }, [avatar, ready]);

    const status: 'idle' | 'loading' | 'shown' | 'failed' = !avatar
        ? 'idle'
        : landed === avatar.slug
          ? 'shown'
          : failed === avatar.slug
            ? 'failed'
            : 'loading';

    const act = (fn: (v: Viewer) => void) => () => viewer.current && fn(viewer.current);
    const hasLook = false; // UI-005: a generated look arrives with the editor; until then Original only.

    const summary =
        status === 'shown' && avatar
            ? `${avatar.name}, ${view === 'free' ? 'free orbit' : `${view} view`}, ${pose === 'rest' ? 'rest pose' : 'relaxed pose'}${turntable ? ', turning' : ''}.`
            : status === 'loading'
              ? `Loading ${avatar?.name ?? 'avatar'}…`
              : status === 'failed'
                ? 'The avatar could not be loaded.'
                : 'No avatar chosen.';

    return (
        <section aria-label="3D viewer" className="relative flex h-full min-h-0 flex-col">
            <div
                className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-surface px-2 py-1.5 whitespace-nowrap"
                role="toolbar"
                aria-label="Viewer mode"
            >
                <ToggleButton
                    pressed={mode === 'original'}
                    onClick={() => {
                        act((v) => v.setMode('original'))();
                        setMode('original');
                    }}
                    icon={<PersonStanding size={16} />}
                >
                    Original
                </ToggleButton>
                <ToggleButton
                    pressed={mode === 'look'}
                    disabled={!hasLook}
                    title="Generate a look to see it here"
                    onClick={() => setMode('look')}
                    icon={<Shirt size={16} />}
                >
                    Look
                </ToggleButton>
                <ToggleButton
                    pressed={mode === 'compare'}
                    disabled={!hasLook}
                    title="Generate a look to compare it with the original"
                    onClick={() => setMode('compare')}
                    icon={<Columns2 size={16} />}
                >
                    Compare
                </ToggleButton>
                <span className="mx-1 h-5 w-px bg-line" aria-hidden />
                <ToggleButton
                    pressed={pose === 'rest'}
                    onClick={() => {
                        const next: Pose = pose === 'rest' ? 'relaxed' : 'rest';
                        act((v) => v.setPose(next))();
                        setPose(next);
                    }}
                    icon={<Footprints size={16} />}
                    title="Rest pose (arms out) shows the fit under the arm"
                >
                    Rest pose
                </ToggleButton>
            </div>

            <div className="relative min-h-0 flex-1 bg-stage">
                <div ref={host} className="viewer-host absolute inset-0 overflow-hidden" data-testid="viewer-host" />
                {status !== 'shown' && (
                    <div className="pointer-events-none absolute inset-0 grid place-items-center text-sm text-muted">
                        <span className="flex items-center gap-2">
                            <Box size={18} aria-hidden />
                            {status === 'loading'
                                ? 'Loading avatar…'
                                : status === 'failed'
                                  ? 'The avatar could not be loaded.'
                                  : 'Choose an avatar to begin.'}
                        </span>
                    </div>
                )}
                <p className="sr-only" aria-live="polite" data-testid="viewer-summary">
                    {summary}
                </p>
            </div>

            <div
                className={`flex shrink-0 items-center gap-1 overflow-x-auto border-t border-line bg-surface px-2 whitespace-nowrap ${compact ? 'py-1' : 'py-1.5'}`}
                role="toolbar"
                aria-label="Camera"
            >
                {VIEWS.map(({ id, label }) => (
                    <ToggleButton
                        key={id}
                        pressed={view === id}
                        disabled={status !== 'shown'}
                        onClick={() => {
                            act((v) => v.inspect(id))();
                            setView(id);
                            setTurntable(false);
                        }}
                    >
                        {label}
                    </ToggleButton>
                ))}
                <span className="mx-1 h-5 w-px bg-line" aria-hidden />
                <ToolbarButton
                    disabled={status !== 'shown'}
                    onClick={act((v) => v.frame())}
                    icon={<Crosshair size={16} />}
                >
                    Reframe
                </ToolbarButton>
                <ToggleButton
                    pressed={turntable}
                    disabled={status !== 'shown'}
                    title={prefersReducedMotion() ? 'Turntable (you asked for reduced motion)' : 'Turn her slowly'}
                    onClick={() => {
                        act((v) => v.setTurntable(!turntable))();
                        setTurntable(!turntable);
                    }}
                    icon={<RotateCw size={16} />}
                >
                    360°
                </ToggleButton>
            </div>
        </section>
    );
}
