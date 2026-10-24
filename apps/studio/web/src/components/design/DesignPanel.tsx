import { CheckCircle2, CircleAlert, ClipboardCheck } from 'lucide-react';
import { useEffect, useState } from 'react';

import { adjustables, outcomes, outfitRequest, type Values } from '@/lib/design';
import { api, type CatalogGarment, type LibraryAvatar, type ParameterSchema, type PlanReport } from '@/lib/forge';
import { PrimaryButton } from '../ui/buttons';
import { ChoiceField, NumberField, ReadOnlyTable } from './fields';

type Loaded = { id: string; schema: ParameterSchema | null; error: string | null };
type Check = { key: string; plan: PlanReport | null; error: string | null; running: boolean };

/**
 * UI-006. The Design view: what Forge lets this garment change, and what its construction is.
 *
 * Every control comes from the garment's parameter schema (GET /v1/catalog/garments/{id}/parameters),
 * so each is a request field Forge reads. "Check with Forge" sends exactly those fields to the plan
 * endpoint — read-only, nothing is built — and shows what Forge made of each one, including any it
 * had to change. Construction is shown, never offered: a request cannot change it.
 */
export function DesignPanel({ garment, avatar }: { garment: CatalogGarment; avatar: LibraryAvatar | null }) {
    const [loaded, setLoaded] = useState<Loaded | null>(null);
    const [values, setValues] = useState<{ id: string; values: Values }>({ id: garment.id, values: {} });
    const [check, setCheck] = useState<Check | null>(null);

    useEffect(() => {
        let live = true;
        api.garmentParameters(garment.id)
            .then((schema) => live && setLoaded({ id: garment.id, schema, error: null }))
            .catch((e: Error) => live && setLoaded({ id: garment.id, schema: null, error: e.message }));
        return () => {
            live = false;
        };
    }, [garment.id]);

    const schema = loaded?.id === garment.id ? loaded.schema : null;
    const error = loaded?.id === garment.id ? loaded.error : null;
    const current = values.id === garment.id ? values.values : {};
    const adultDeclared = Boolean(avatar?.depictsAdult);
    const key = JSON.stringify([garment.id, avatar?.slug, current]);
    const result = check?.key === key ? check : null;

    const set = (field: string, value: string | number | undefined) => {
        const next = { ...current };
        if (value === undefined) delete next[field];
        else next[field] = value;
        setValues({ id: garment.id, values: next });
    };

    const runCheck = () => {
        if (!schema || !avatar) return;
        setCheck({ key, plan: null, error: null, running: true });
        api.planLibrary(avatar.slug, {
            outfit: outfitRequest(schema, current),
            options: { renderPreview: false, engine: 'native' },
        })
            .then((plan) => setCheck({ key, plan, error: null, running: false }))
            .catch((e: Error) => setCheck({ key, plan: null, error: e.message, running: false }));
    };

    if (error) return <p className="text-sm text-bad">Forge could not describe this garment: {error}</p>;
    if (!schema) return <p className="text-sm text-muted">Reading this garment's construction…</p>;

    const controls = adjustables(schema);
    return (
        <div className="space-y-5">
            <section aria-labelledby="design-adjust" className="space-y-4">
                <h3 id="design-adjust" className="text-base font-semibold">
                    What you can change
                </h3>
                {controls.length === 0 && <p className="text-sm text-muted">Nothing on this garment is adjustable.</p>}
                {controls.map((p) =>
                    p.type === 'number' ? (
                        <NumberField
                            key={p.id}
                            parameter={p}
                            value={current[p.requestField] as number | undefined}
                            adultDeclared={adultDeclared}
                            onChange={(v) => set(p.requestField, v)}
                        />
                    ) : (
                        <ChoiceField
                            key={p.id}
                            parameter={p}
                            value={current[p.requestField] as string | undefined}
                            adultDeclared={adultDeclared}
                            onChange={(v) => set(p.requestField, v)}
                        />
                    ),
                )}
                <div className="space-y-2">
                    <PrimaryButton
                        icon={<ClipboardCheck size={16} />}
                        onClick={runCheck}
                        disabled={!avatar || result?.running}
                    >
                        {result?.running ? 'Checking…' : 'Check with Forge'}
                    </PrimaryButton>
                    <p className="text-xs text-muted">
                        Asks Forge what it would build on {avatar?.name ?? 'the avatar'}; nothing is generated.
                    </p>
                    <div aria-live="polite">
                        {result?.error && <p className="text-sm text-bad">Forge refused the check: {result.error}</p>}
                        {result?.plan && <CheckResult schema={schema} values={current} plan={result.plan} />}
                    </div>
                </div>
            </section>

            {schema.groups
                .filter((g) => !g.adjustable)
                .map((g) => (
                    <section key={g.id} aria-labelledby={`design-${g.id}`} className="space-y-2">
                        <h3 id={`design-${g.id}`} className="text-base font-semibold">
                            {g.label}
                        </h3>
                        {!g.adjustable && <ReadOnlyTable parameters={g.parameters} />}
                    </section>
                ))}

            <details className="rounded-lg border border-line p-3 text-sm">
                <summary className="cursor-pointer font-medium">Not offered yet, and why</summary>
                <ul className="mt-2 space-y-1.5 text-muted">
                    {schema.notExposed.map((n) => (
                        <li key={n.field}>
                            <span className="font-medium text-ink capitalize">{n.field}</span> — {n.reason}
                        </li>
                    ))}
                </ul>
            </details>
        </div>
    );
}

function CheckResult({ schema, values, plan }: { schema: ParameterSchema; values: Values; plan: PlanReport }) {
    const sheet = plan.garments.find((g) => g.template === schema.templateId) ?? plan.garments[0];
    const rows = outcomes(schema, values, plan);
    return (
        <div className="space-y-2 rounded-lg border border-line bg-raised p-3 text-sm" data-testid="check-result">
            <p className="flex items-center gap-1.5 font-medium">
                {plan.allowed ? (
                    <CheckCircle2 size={16} className="text-ok" aria-hidden />
                ) : (
                    <CircleAlert size={16} className="text-bad" aria-hidden />
                )}
                {plan.allowed ? 'Forge would build this.' : `Forge would refuse: ${sheet?.refusal ?? 'see the plan'}`}
            </p>
            {rows.length === 0 ? (
                <p className="text-muted">Nothing changed from the design.</p>
            ) : (
                <ul className="space-y-1">
                    {rows.map((r) => (
                        <li key={r.field} className="flex justify-between gap-2">
                            <span>{r.label}</span>
                            <span className={r.honoured ? '' : 'text-warn'}>
                                {String(r.resolved)}
                                {!r.honoured && ` (asked ${r.requested})`}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
            {sheet && <p className="text-xs text-muted">Lining: {sheet.lining}.</p>}
        </div>
    );
}
