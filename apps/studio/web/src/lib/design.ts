import type { AdjustableChoice, AdjustableNumber, ParameterSchema, PlanReport } from './forge';

export type Adjustable = AdjustableChoice | AdjustableNumber;
/** Values the person has set, by requestField. Absent means "as designed": nothing is sent. */
export type Values = Record<string, string | number>;

export function adjustables(schema: ParameterSchema | null): Adjustable[] {
    if (!schema) return [];
    return schema.groups.flatMap((g) => (g.adjustable ? g.parameters : []));
}

/**
 * The outfit request for a library job or plan: the garment's own template, and exactly the
 * request fields the schema names, for the values the person set. Nothing the schema did not
 * offer can be sent, so the request can only carry fields Forge reads.
 */
export function outfitRequest(schema: ParameterSchema, values: Values): Record<string, unknown> {
    const outfit: Record<string, unknown> = { prompt: schema.name, mode: 'template', templateId: schema.templateId };
    for (const parameter of adjustables(schema)) {
        const value = values[parameter.requestField];
        if (value !== undefined) outfit[parameter.requestField] = value;
    }
    return outfit;
}

/** Whether a value needs the avatar declared adult (the server decides; this only explains). */
export function gated(parameter: Adjustable, value: string | number | undefined): boolean {
    if (value === undefined) return false;
    if (parameter.type === 'number') {
        const below = parameter.requiresAdultDeclarationBelow;
        return below !== undefined && Number(value) < below;
    }
    return Boolean(parameter.options.find((o) => o.value === value)?.requiresAdultDeclaration);
}

export interface Outcome {
    field: string;
    label: string;
    requested: string | number;
    resolved: string | number | null;
    honoured: boolean;
}

/** What Forge made of each value the person set, from the plan's design sheet. */
export function outcomes(schema: ParameterSchema, values: Values, plan: PlanReport): Outcome[] {
    const sheet = plan.garments.find((g) => g.template === schema.templateId) ?? plan.garments[0];
    if (!sheet) return [];
    const resolved: Record<string, string | number | null> = {
        color: sheet.baseColor,
        finish: sheet.finish,
        pattern: sheet.pattern,
        opacity: sheet.opacity,
    };
    return adjustables(schema)
        .filter((p) => values[p.requestField] !== undefined)
        .map((p) => {
            const requested = values[p.requestField];
            const got = resolved[p.requestField] ?? null;
            return { field: p.requestField, label: p.label, requested, resolved: got, honoured: got === requested };
        });
}
