import { describe, expect, it } from 'vitest';

import { filterGarments, flatten } from './catalog';
import type { Catalog, CatalogGarment } from './forge';

function garment(over: Partial<CatalogGarment>): CatalogGarment {
    return {
        id: 'x',
        name: 'X',
        description: '',
        category: 'top',
        tags: [],
        silhouette: '',
        hem: '',
        sleeve: '',
        previewStatus: 'ready',
        previewUrl: '/p.webp',
        requiresAdult: false,
        supportsColor: true,
        availableColors: [],
        supportedMaterials: [],
        ...over,
    };
}

const catalog: Catalog = {
    schemaVersion: 1,
    totalTemplates: 3,
    visibleCount: 3,
    previewCount: 2,
    categories: [
        {
            id: 'top',
            label: 'Tops',
            count: 2,
            garments: [
                garment({ id: 'tee', name: 'Cropped Tee', tags: ['casual'] }),
                garment({
                    id: 'cami',
                    name: 'Lace Cami',
                    tags: ['lace', 'evening'],
                    previewStatus: 'pending',
                    previewUrl: null,
                }),
            ],
        },
        {
            id: 'dress',
            label: 'Dresses',
            count: 1,
            garments: [garment({ id: 'mini', name: 'Bodycon Mini', category: 'dress', silhouette: 'sheath' })],
        },
    ],
};

describe('gallery filtering', () => {
    it('keeps the server order across categories', () => {
        expect(flatten(catalog).map((g) => g.id)).toEqual(['tee', 'cami', 'mini']);
    });
    it('matches every word against name, tags and shape', () => {
        const all = { category: 'all', previewedOnly: false };
        expect(filterGarments(catalog, { ...all, query: 'lace evening' }).map((g) => g.id)).toEqual(['cami']);
        expect(filterGarments(catalog, { ...all, query: 'SHEATH' }).map((g) => g.id)).toEqual(['mini']);
        expect(filterGarments(catalog, { ...all, query: 'lace mini' })).toEqual([]);
    });
    it('filters by category and by whether a real preview exists', () => {
        expect(filterGarments(catalog, { query: '', category: 'top', previewedOnly: true }).map((g) => g.id)).toEqual([
            'tee',
        ]);
    });
    it('shows nothing for a missing catalogue rather than failing', () => {
        expect(filterGarments(null, { query: '', category: 'all', previewedOnly: false })).toEqual([]);
    });
});
