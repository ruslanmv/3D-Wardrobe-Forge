// UI-002. The Studio's one door to Forge is still apps/studio/js/api.js: the React Studio imports
// it rather than growing a second client, so both Studios send the same headers and handle the
// same errors. Types live beside it (api.d.ts).
export { ApiError, admin, api, auth } from '../../../js/api.js';
export type {
    AdminStatus,
    Capabilities,
    Catalog,
    CatalogCategory,
    CatalogGarment,
    Library,
    LibraryAvatar,
    AdjustableChoice,
    AdjustableNumber,
    ParameterGroup,
    ParameterSchema,
    PlanReport,
    ReadOnlyParameter,
} from '../../../js/api.js';
