import { describe, expect, it } from 'vitest';

import { gated, outcomes, outfitRequest } from './design';
import type { ParameterSchema, PlanReport } from './forge';

const schema: ParameterSchema = {
    schemaVersion: 1,
    templateId: 'dress-mini-bodycon-v1',
    name: 'Bodycon Mini Dress',
    category: 'dress',
    requiresAdult: false,
    notExposed: [],
    groups: [
        {
            id: 'material',
            label: 'Material',
            adjustable: true,
            parameters: [
                {
                    id: 'finish',
                    label: 'Finish',
                    type: 'choice',
                    requestField: 'finish',
                    default: 'matte',
                    source: 'template material policy',
                    description: '',
                    options: [
                        { value: 'matte', label: 'matte' },
                        { value: 'gloss', label: 'gloss' },
                    ],
                },
                {
                    id: 'pattern',
                    label: 'Pattern',
                    type: 'choice',
                    requestField: 'pattern',
                    default: 'none',
                    source: 'template material policy',
                    description: '',
                    options: [
                        { value: 'none', label: 'none' },
                        { value: 'fishnet', label: 'fishnet', requiresAdultDeclaration: true },
                    ],
                },
                {
                    id: 'opacity',
                    label: 'Opacity',
                    type: 'number',
                    requestField: 'opacity',
                    unit: 'fraction',
                    min: 0.2,
                    max: 1,
                    step: 0.05,
                    default: 1,
                    requiresAdultDeclarationBelow: 1,
                    source: 'template material policy',
                    description: '',
                },
            ],
        },
        {
            id: 'shape',
            label: 'Shape',
            adjustable: false,
            parameters: [
                {
                    id: 'fit.conform',
                    label: 'Conformity',
                    unit: 'fraction',
                    value: 0.95,
                    source: 'template',
                    description: '',
                },
            ],
        },
    ],
};

describe('the design request', () => {
    it('sends the template and only the fields the person set', () => {
        expect(outfitRequest(schema, { finish: 'gloss' })).toEqual({
            prompt: 'Bodycon Mini Dress',
            mode: 'template',
            templateId: 'dress-mini-bodycon-v1',
            finish: 'gloss',
        });
    });
    it('cannot carry a field the schema did not offer', () => {
        expect(outfitRequest(schema, { coverage: 'micro', finish: 'gloss' })).not.toHaveProperty('coverage');
    });
});

describe('the adult gate, as explained to the person', () => {
    it('marks see-through values only', () => {
        const [, pattern, opacity] = schema.groups[0].parameters as never[];
        expect(gated(pattern, 'fishnet')).toBe(true);
        expect(gated(pattern, 'none')).toBe(false);
        expect(gated(opacity, 0.6)).toBe(true);
        expect(gated(opacity, 1)).toBe(false);
        expect(gated(opacity, undefined)).toBe(false);
    });
});

describe('what Forge made of it', () => {
    it('compares each value set with the plan, and says when one was changed', () => {
        const plan = {
            name: 'x',
            allowed: true,
            garments: [
                {
                    garment: 'g',
                    template: 'dress-mini-bodycon-v1',
                    allowed: true,
                    refusal: null,
                    baseColor: null,
                    finish: 'gloss',
                    pattern: 'none',
                    opacity: 1,
                    alphaMode: 'opaque',
                    lining: 'opaque fabric',
                },
            ],
        } as PlanReport;
        expect(outcomes(schema, { finish: 'gloss', opacity: 0.6 }, plan)).toEqual([
            { field: 'finish', label: 'Finish', requested: 'gloss', resolved: 'gloss', honoured: true },
            { field: 'opacity', label: 'Opacity', requested: 0.6, resolved: 1, honoured: false },
        ]);
    });
});
