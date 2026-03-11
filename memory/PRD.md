# PRD — Amazon-inspired E-commerce Recommender

## Original Problem Statement
Build an Amazon-inspired e-commerce application with React + Tailwind frontend and FastAPI (Polars) backend.

Required from initial statement:
- Amazon product-detail style UI (nav colors: `#131921`, `#232f3e`, links `#007185`, buttons `#FFD814`)
- Product detail page with two-column layout and VND pricing
- Endpoint `/api/recommendations/{item_id}` based on co-purchase mining from parquet files
- Recommendations must include only `sale_status == 1`
- Clicking recommendation updates main product and refreshes recommendation list
- Currency formatting in `vi-VN`
- Start app on `item_id=000804000046`

User-confirmed expansion:
- Add searchable/sortable/filterable full-catalog shop page
- Add second recommendation stream: “Relevant” substitutes by category/brand
- Use data path `/app/data/items.parquet` and `/app/data/transactions-2025-12.parquet`
- Use styled “No image available” placeholder
- Keep selected product in URL query (`?item_id=...`)

## Architecture Decisions
- **Frontend:** React + Tailwind + shadcn/ui primitives, query-driven view state (`item_id` / `view`)
- **Backend:** FastAPI + Polars for parquet-native analytics (no DB dependency for catalog/recommendations)
- **Data strategy:** Canonicalized column mapping to tolerate common schema variations (`item_id`, `name`, `brand`, etc.)
- **Recommendation logic:**
  - Frequently Bought Together = shared-customer co-purchase frequency ranking (top 5)
  - Relevant = category/brand relevance score + price proximity ranking (top 5)
- **Formatting:** frontend currency helper with `Intl.NumberFormat('vi-VN', { currency: 'VND' })`

## User Personas
- **Deal-driven shopper:** wants quick filtering/sorting and related options at similar prices
- **Discovery shopper:** explores alternatives and bundles from recommendation trays
- **Efficiency shopper:** expects Amazon-like dense UI and quick product switching

## Core Requirements (Static)
1. Amazon-inspired visual system and dense product page
2. Shop catalog with search/filter/sort
3. Product detail for selected `item_id`
4. Two recommendation streams (transactional + metadata-based)
5. URL-synced product selection
6. `vi-VN` currency formatting
7. Recommendation and catalog output constrained to active sale status

## What’s Implemented
### 2026-03-11
- Implemented FastAPI endpoints:
  - `GET /api/items/meta`
  - `GET /api/items`
  - `GET /api/items/{item_id}`
  - `GET /api/recommendations/{item_id}`
- Implemented Polars pipeline to read parquet files and compute:
  - customer cohort for target item
  - co-purchase frequency ranking
  - enriched metadata joins and active-item filtering
  - relevant substitutes by category/brand scoring
- Built Amazon-inspired frontend:
  - top nav + sub-nav with target colors
  - shop page with sidebar filters, sorting, pagination, and product grid
  - product detail page with two-column layout and no-image placeholder
  - Frequently Bought Together and Relevant horizontal trays
  - click-through product transitions with URL query updates
- Added `data-testid` across interactive and critical display elements.
- Added local parquet seed files under `/app/data` for functional end-to-end operation.
- Validation complete:
  - manual API checks via external backend URL
  - frontend screenshot flow checks
  - testing agent regression (backend + frontend) with no blocking defects

## Prioritized Backlog
### P0 (Next Critical)
- Add product-image URL support from catalog source when available (replace placeholders)
- Add robust empty-state UX when filters return zero products

### P1 (High Value)
- Add sort by popularity/frequency from transaction aggregates
- Add recommendation confidence labels (e.g., “Bought together by X customers”)
- Add shop filter chips and clear individual chip controls

### P2 (Enhancements)
- Add mini-cart and persisted recently viewed list
- Add analytics events for recommendation click-through and conversion funnel
- Add performance caching layer for larger parquet datasets

## Next Tasks List
1. Connect real production parquet files (if different from seeded local dataset)
2. Add image column handling and product media rendering
3. Extend recommendation explainability UI
4. Introduce cart workflow in next iteration if requested
