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

/** UI-006. One value in a garment's parameter schema (GET /v1/catalog/garments/{id}/parameters). */
export type ParameterSource = 'template' | 'preset' | 'default' | 'reference' | 'template material policy';

export interface ChoiceOption {
    value: string;
    label: string;
    hex?: string;
    requiresAdultDeclaration?: boolean;
}

export interface AdjustableChoice {
    id: string;
    label: string;
    type: 'choice';
    requestField: string;
    options: ChoiceOption[];
    default: string | null;
    source: ParameterSource;
    description: string;
}

export interface AdjustableNumber {
    id: string;
    label: string;
    type: 'number';
    requestField: string;
    unit: string;
    min: number;
    max: number;
    step: number;
    default: number;
    requiresAdultDeclarationBelow?: number;
    source: ParameterSource;
    description: string;
}

export interface ReadOnlyParameter {
    id: string;
    label: string;
    unit: string;
    value: string | number | boolean | null;
    source: ParameterSource;
    description: string;
}

export type ParameterGroup =
    | { id: string; label: string; adjustable: true; parameters: (AdjustableChoice | AdjustableNumber)[] }
    | { id: string; label: string; adjustable: false; parameters: ReadOnlyParameter[] };

export interface ParameterSchema {
    schemaVersion: number;
    templateId: string;
    name: string;
    category: string;
    requiresAdult: boolean;
    groups: ParameterGroup[];
    notExposed: { field: string; reason: string }[];
}

/** The parts of POST /v1/library/{slug}/plan the Design view reads. */
export interface PlanGarment {
    garment: string;
    template: string | null;
    allowed: boolean;
    refusal: string | null;
    baseColor: string | null;
    finish: string;
    pattern: string;
    opacity: number;
    alphaMode: string;
    lining: string;
    [key: string]: unknown;
}

export interface PlanReport {
    name: string;
    allowed: boolean;
    garments: PlanGarment[];
    [key: string]: unknown;
}

export declare const api: {
    capabilities(): Promise<Capabilities>;
    library(): Promise<Library>;
    vocabulary(): Promise<Record<string, unknown>>;
    catalogGarments(options?: { category?: string; includeRestricted?: boolean }): Promise<Catalog>;
    adminStatus(): Promise<AdminStatus>;
    garmentParameters(templateId: string): Promise<ParameterSchema>;
    planLibrary(slug: string, body: Record<string, unknown>): Promise<PlanReport>;
    /** An object URL for a protected asset. The caller owns it and must revoke it. */
    blobUrl(path: string): Promise<string>;
    [method: string]: unknown;
};
