// UI-003. The types of viewer.js for the React Studio (apps/studio/web). viewer.js stays plain
// JavaScript, served as is to the vanilla Studio; this file only describes it.

export type Slot = 'original' | 'look';
export type ViewMode = 'original' | 'look' | 'compare';
export type Pose = 'relaxed' | 'rest';
export type InspectView = 'front' | 'side' | 'back' | 'free';

export declare function correctiveWeight(downDegrees: number, keys: [number, number][]): number;

export declare class Viewer {
    constructor(container: HTMLElement);
    readonly mode: ViewMode;
    readonly pose: Pose;
    view: InspectView;
    immersive: boolean;
    onTap: (() => void) | null;
    onDoubleTap: (() => void) | null;
    dispose(): void;
    resize(): void;
    comparing(): boolean;
    inspect(view?: InspectView): void;
    reset(): void;
    orbitFor(view: InspectView): void;
    polarDegrees(): number;
    /** True when this load is the latest for its slot and landed; false when a later one superseded it. */
    load(slot: Slot, url: string): Promise<boolean>;
    clear(slot: Slot, options?: { keepToken?: boolean }): void;
    has(slot: Slot): boolean;
    setMode(mode: ViewMode): void;
    setPose(pose: Pose): void;
    setTurntable(on: boolean): void;
    frame(): void;
    turnTo(facing?: 'front' | 'back' | 'left' | 'right'): void;
    snapshot(): string;
}
