// UI-002. The types of api.js for the React Studio. Field shapes follow the recorded contract
// (tests/fixtures/studio-contract.json); only what the new Studio reads is typed here.

export declare class ApiError extends Error {
    status: number;
    detail: unknown;
}

export declare const auth: { key: string };
export declare const admin: { token: string };

export interface CatalogGarment {
    id: string;
    name: string;
    description: string;
    category: string;
    tags: string[];
    silhouette: string;
    hem: string;
    sleeve: string;
    previewStatus: 'ready' | 'pending' | string;
    previewUrl: string | null;
    requiresAdult: boolean;
    supportsColor: boolean;
    availableColors: string[];
    supportedMaterials: string[];
}

export interface CatalogCategory {
    id: string;
    label: string;
    count: number;
    garments: CatalogGarment[];
}

export interface Catalog {
    schemaVersion: number;
    totalTemplates: number;
    visibleCount: number;
    previewCount: number;
    categories: CatalogCategory[];
}

export interface LibraryAvatar {
    slug: string;
    name: string;
    available: boolean;
    depictsAdult: boolean;
    license: string;
    fileUrl: string;
    sha256: string;
    source: string;
    collection: string;
    presentation: string | null;
    problem: string | null;
}

export interface Library {
    avatars: LibraryAvatar[];
    licenseNote: string;
    problem: string | null;
}

export interface Capabilities {
    version: string;
    provider: string;
    templates: number;
    categories: string[];
    auth: { mode: string; keyRequired: boolean; trusted: boolean | null };
    [key: string]: unknown;
}

export interface AdminStatus {
    enabled: boolean;
    signedIn: boolean;
    session: unknown;
    unavailable: unknown;
    username: string | null;
    minPasswordLength: number;
}

export declare const api: {
    capabilities(): Promise<Capabilities>;
    library(): Promise<Library>;
    vocabulary(): Promise<Record<string, unknown>>;
    catalogGarments(options?: { category?: string; includeRestricted?: boolean }): Promise<Catalog>;
    adminStatus(): Promise<AdminStatus>;
    /** An object URL for a protected asset. The caller owns it and must revoke it. */
    blobUrl(path: string): Promise<string>;
    [method: string]: unknown;
};
