import type { Catalog, CatalogGarment } from './forge';

/** Every garment the server listed, in its category order. */
export function flatten(catalog: Catalog | null): CatalogGarment[] {
    return catalog ? catalog.categories.flatMap((category) => category.garments) : [];
}

export interface GalleryFilter {
    query: string;
    category: string; // 'all' or a category id
    previewedOnly: boolean;
}

/** Words of the query that must all appear in a garment's name, description, tags or shape fields. */
function words(query: string): string[] {
    return query
        .toLowerCase()
        .split(/\s+/)
        .map((w) => w.trim())
        .filter(Boolean);
}

export function matches(garment: CatalogGarment, filter: GalleryFilter): boolean {
    if (filter.category !== 'all' && garment.category !== filter.category) return false;
    if (filter.previewedOnly && garment.previewStatus !== 'ready') return false;
    const haystack = [
        garment.name,
        garment.description,
        garment.silhouette,
        garment.hem,
        garment.sleeve,
        ...garment.tags,
    ]
        .join(' ')
        .toLowerCase();
    return words(filter.query).every((word) => haystack.includes(word));
}

export function filterGarments(catalog: Catalog | null, filter: GalleryFilter): CatalogGarment[] {
    return flatten(catalog).filter((garment) => matches(garment, filter));
}
