import { useEffect, useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchCatalog, fetchFilterMeta, fetchSearchRecommendations } from "@/lib/api";
import { formatVnd } from "@/lib/currency";

const PAGE_SIZE = 20;

const StatusBadge = ({ saleStatus, testId }) => (
  <span
    className={`inline-flex w-fit rounded-full px-2 py-0.5 text-[11px] font-medium ${Number(saleStatus) === 1 ? "bg-[#e7f8ee] text-[#067d2f]" : "bg-[#f3f4f6] text-[#6b7280]"}`}
    data-testid={testId}
  >
    item_status: {saleStatus}
  </span>
);

const ProductCard = ({ item, onOpenItem }) => (
  <button
    type="button"
    className="flex h-full flex-col border border-[#e7e7e7] bg-white p-3 text-left transition-colors hover:bg-[#f9f9f9]"
    onClick={() => onOpenItem(item.item_id)}
    data-testid={`product-card-${item.item_id}`}
  >
    <div className="mb-2 text-xs text-[#565959]" data-testid={`product-card-id-${item.item_id}`}>
      {item.item_id}
    </div>
    <h3 className="line-clamp-2 min-h-[40px] text-[13px] font-medium" data-testid={`product-card-name-${item.item_id}`}>
      {item.name}
    </h3>
    <p className="mt-1 text-xs text-[#007185]" data-testid={`product-card-brand-${item.item_id}`}>
      {item.brand}
    </p>
    <div className="mt-2" data-testid={`product-card-status-wrapper-${item.item_id}`}>
      <StatusBadge saleStatus={item.sale_status} testId={`product-card-status-${item.item_id}`} />
    </div>
    <p className="mt-auto pt-2 text-base font-bold text-[#B12704]" data-testid={`product-card-price-${item.item_id}`}>
      {formatVnd(item.price)}
    </p>
  </button>
);

const SearchRecommendationCard = ({ item, sectionId, onOpenItem, showUpsellMeta = false }) => (
  <button
    type="button"
    onClick={() => onOpenItem(item.item_id)}
    className="w-[220px] flex-shrink-0 border border-[#e7e7e7] bg-white p-3 text-left hover:bg-[#f9f9f9]"
    data-testid={`${sectionId}-card-${item.item_id}`}
  >
    <p className="text-xs text-[#565959]" data-testid={`${sectionId}-card-id-${item.item_id}`}>
      {item.item_id}
    </p>
    <p className="mt-1 line-clamp-2 min-h-[34px] text-[13px] font-medium" data-testid={`${sectionId}-card-name-${item.item_id}`}>
      {item.name}
    </p>
    <div className="mt-2" data-testid={`${sectionId}-card-status-wrapper-${item.item_id}`}>
      <StatusBadge saleStatus={item.sale_status} testId={`${sectionId}-card-status-${item.item_id}`} />
    </div>
    {showUpsellMeta && (
      <div className="mt-2 text-xs text-[#565959]" data-testid={`${sectionId}-card-upsell-meta-${item.item_id}`}>
        <p data-testid={`${sectionId}-card-size-${item.item_id}`}>Size: {item.size || "N/A"}</p>
        <p data-testid={`${sectionId}-card-score-${item.item_id}`}>Score: {Number(item.score || 0)}</p>
      </div>
    )}
    <p className="mt-2 text-sm font-bold text-[#B12704]" data-testid={`${sectionId}-card-price-${item.item_id}`}>
      {formatVnd(item.price)}
    </p>
  </button>
);

export const ShopPage = ({ initialQuery, onOpenItem }) => {
  const [searchText, setSearchText] = useState(initialQuery);
  const [category, setCategory] = useState("");
  const [brand, setBrand] = useState("");
  const [sortBy, setSortBy] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState([]);
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchRecommendationData, setSearchRecommendationData] = useState({
    matched_item_id: null,
    similar_items: [],
    upsell_recommendations: [],
    is_ta_query: false,
  });
  const [searchRecommendationLoading, setSearchRecommendationLoading] = useState(false);
  const [searchRecommendationError, setSearchRecommendationError] = useState("");

  useEffect(() => {
    setSearchText(initialQuery);
    setOffset(0);
  }, [initialQuery]);

  useEffect(() => {
    const loadMeta = async () => {
      try {
        const meta = await fetchFilterMeta();
        setCategories(meta.categories || []);
        setBrands(meta.brands || []);
      } catch {
        setCategories([]);
        setBrands([]);
      }
    };

    loadMeta();
  }, []);

  const queryParams = useMemo(
    () => ({
      q: searchText,
      category,
      brand,
      sort_by: sortBy,
      sort_dir: sortDir,
      limit: PAGE_SIZE,
      offset,
    }),
    [searchText, category, brand, sortBy, sortDir, offset],
  );

  useEffect(() => {
    const loadCatalog = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await fetchCatalog(queryParams);
        setItems(response.items || []);
        setTotal(response.total || 0);
      } catch (fetchError) {
        const message = fetchError?.response?.data?.detail || "Không thể tải danh mục sản phẩm.";
        setError(message);
        setItems([]);
      } finally {
        setLoading(false);
      }
    };

    loadCatalog();
  }, [queryParams]);

  useEffect(() => {
    const queryValue = searchText.trim();
    if (!queryValue) {
      setSearchRecommendationData({
        matched_item_id: null,
        similar_items: [],
        upsell_recommendations: [],
        is_ta_query: false,
      });
      setSearchRecommendationError("");
      setSearchRecommendationLoading(false);
      return;
    }

    const loadSearchRecommendations = async () => {
      setSearchRecommendationLoading(true);
      setSearchRecommendationError("");

      try {
        const response = await fetchSearchRecommendations(queryValue);
        setSearchRecommendationData({
          matched_item_id: response?.matched_item_id || null,
          similar_items: response?.similar_items || [],
          upsell_recommendations: response?.upsell_recommendations || [],
          is_ta_query: Boolean(response?.is_ta_query),
        });
      } catch (fetchError) {
        const message = fetchError?.response?.data?.detail || "Không thể tải gợi ý từ recommendations_all.json.";
        setSearchRecommendationError(message);
        setSearchRecommendationData({
          matched_item_id: null,
          similar_items: [],
          upsell_recommendations: [],
          is_ta_query: false,
        });
      } finally {
        setSearchRecommendationLoading(false);
      }
    };

    loadSearchRecommendations();
  }, [searchText]);

  const handleResetFilters = () => {
    setSearchText("");
    setCategory("");
    setBrand("");
    setSortBy("name");
    setSortDir("asc");
    setOffset(0);
  };

  const pageStart = offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const hasActiveSearch = Boolean(searchText.trim());
  const hasSimilarItems = searchRecommendationData.similar_items.length > 0;
  const hasUpsellItems = searchRecommendationData.upsell_recommendations.length > 0;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]" data-testid="shop-page">
      <aside className="h-fit border border-[#e7e7e7] bg-white p-3" data-testid="shop-sidebar-filters">
        <h2 className="mb-3 text-sm font-bold" data-testid="shop-filter-title">
          Bộ lọc tìm kiếm
        </h2>
        <div className="space-y-3">
          <label className="block text-xs font-medium" data-testid="shop-search-label">
            Từ khóa
            <div className="relative mt-1">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-[#565959]" />
              <Input
                value={searchText}
                onChange={(event) => {
                  setSearchText(event.target.value);
                  setOffset(0);
                }}
                className="h-9 border-[#d5d9d9] bg-white pl-8 text-[13px] focus-visible:ring-[#E77600]"
                data-testid="shop-search-input"
              />
            </div>
          </label>

          <label className="block text-xs font-medium" data-testid="shop-category-label">
            Danh mục
            <select
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                setOffset(0);
              }}
              className="mt-1 h-9 w-full border border-[#d5d9d9] bg-white px-2 text-[13px]"
              data-testid="shop-category-select"
            >
              <option value="">Tất cả danh mục</option>
              {categories.map((itemCategory) => (
                <option key={itemCategory} value={itemCategory}>
                  {itemCategory}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-medium" data-testid="shop-brand-label">
            Thương hiệu
            <select
              value={brand}
              onChange={(event) => {
                setBrand(event.target.value);
                setOffset(0);
              }}
              className="mt-1 h-9 w-full border border-[#d5d9d9] bg-white px-2 text-[13px]"
              data-testid="shop-brand-select"
            >
              <option value="">Tất cả thương hiệu</option>
              {brands.map((itemBrand) => (
                <option key={itemBrand} value={itemBrand}>
                  {itemBrand}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-medium" data-testid="shop-sort-by-label">
            Sắp xếp theo
            <select
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value)}
              className="mt-1 h-9 w-full border border-[#d5d9d9] bg-white px-2 text-[13px]"
              data-testid="shop-sort-by-select"
            >
              <option value="name">Tên sản phẩm</option>
              <option value="price">Giá</option>
              <option value="brand">Thương hiệu</option>
              <option value="item_id">Mã sản phẩm</option>
            </select>
          </label>

          <label className="block text-xs font-medium" data-testid="shop-sort-dir-label">
            Thứ tự
            <select
              value={sortDir}
              onChange={(event) => setSortDir(event.target.value)}
              className="mt-1 h-9 w-full border border-[#d5d9d9] bg-white px-2 text-[13px]"
              data-testid="shop-sort-dir-select"
            >
              <option value="asc">Tăng dần</option>
              <option value="desc">Giảm dần</option>
            </select>
          </label>

          <Button
            type="button"
            onClick={handleResetFilters}
            className="h-9 w-full rounded-full border border-[#D5D9D9] bg-white text-black hover:bg-[#f7fafa]"
            data-testid="shop-reset-filters-button"
          >
            Xóa bộ lọc
          </Button>
        </div>
      </aside>

      <section className="space-y-3" data-testid="shop-results-section">
        <div className="flex flex-wrap items-center justify-between gap-2 border border-[#e7e7e7] bg-white px-3 py-2">
          <h1 className="text-base font-bold" data-testid="shop-results-title">
            Shop sản phẩm
          </h1>
          <p className="text-xs text-[#565959]" data-testid="shop-results-count">
            {total > 0 ? `Hiển thị ${pageStart}-${pageEnd} / ${total} sản phẩm` : "Không có sản phẩm"}
          </p>
        </div>

        {hasActiveSearch && (
          <section className="space-y-3 border border-[#e7e7e7] bg-white p-3" data-testid="shop-search-recommendations-section">
            <h2 className="text-sm font-bold" data-testid="shop-search-recommendations-title">
              Search recommendations from JSON
            </h2>
            <p className="text-xs text-[#565959]" data-testid="shop-search-recommendations-meta">
              Query: <span className="font-medium">{searchText.trim()}</span>
              {searchRecommendationData.matched_item_id ? ` • matched item: ${searchRecommendationData.matched_item_id}` : ""}
            </p>

            {searchRecommendationLoading ? (
              <div className="flex items-center gap-2 text-xs text-[#565959]" data-testid="shop-search-recommendations-loading">
                <Loader2 className="h-4 w-4 animate-spin" />
                Đang tải similar/upsell từ recommendations_all.json...
              </div>
            ) : searchRecommendationError ? (
              <p className="text-xs text-[#B12704]" data-testid="shop-search-recommendations-error">
                {searchRecommendationError}
              </p>
            ) : !searchRecommendationData.matched_item_id ? (
              <p className="text-xs text-[#565959]" data-testid="shop-search-recommendations-empty">
                Không tìm thấy item_id phù hợp cho từ khóa này.
              </p>
            ) : (
              <>
                <div className="space-y-2" data-testid="shop-similar-items-block">
                  <h3 className="text-sm font-semibold" data-testid="shop-similar-items-title">
                    Similar items (name + price)
                  </h3>
                  {hasSimilarItems ? (
                    <div className="amazon-scrollbar flex gap-3 overflow-x-auto pb-2" data-testid="shop-similar-items-list">
                      {searchRecommendationData.similar_items.map((item) => (
                        <SearchRecommendationCard
                          key={`similar-${item.item_id}`}
                          item={item}
                          onOpenItem={onOpenItem}
                          sectionId="shop-similar-items"
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-[#565959]" data-testid="shop-similar-items-empty">
                      recommendations_all.json không có similar_items cho item này.
                    </p>
                  )}
                </div>

                {searchRecommendationData.is_ta_query && (
                  <div className="space-y-2" data-testid="shop-upsell-items-block">
                    <h3 className="text-sm font-semibold" data-testid="shop-upsell-items-title">
                      Upsell recommendations (top 5 score)
                    </h3>
                    {hasUpsellItems ? (
                      <div className="amazon-scrollbar flex gap-3 overflow-x-auto pb-2" data-testid="shop-upsell-items-list">
                        {searchRecommendationData.upsell_recommendations.map((item) => (
                          <SearchRecommendationCard
                            key={`upsell-${item.item_id}`}
                            item={item}
                            onOpenItem={onOpenItem}
                            sectionId="shop-upsell-items"
                            showUpsellMeta
                          />
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-[#565959]" data-testid="shop-upsell-items-empty">
                        Không có upsell_recommendations cho từ khóa tã.
                      </p>
                    )}
                  </div>
                )}
              </>
            )}
          </section>
        )}

        {loading ? (
          <div className="flex min-h-[220px] items-center justify-center border border-[#e7e7e7] bg-white" data-testid="shop-loading-state">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Đang tải sản phẩm...
          </div>
        ) : error ? (
          <div className="border border-[#e7e7e7] bg-white p-4 text-sm text-[#B12704]" data-testid="shop-error-message">
            {error}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="shop-product-grid">
              {items.map((item) => (
                <ProductCard key={item.item_id} item={item} onOpenItem={onOpenItem} />
              ))}
            </div>
            <div className="flex items-center justify-end gap-2 border border-[#e7e7e7] bg-white px-3 py-2" data-testid="shop-pagination-controls">
              <Button
                type="button"
                onClick={() => setOffset((current) => Math.max(current - PAGE_SIZE, 0))}
                disabled={offset === 0}
                className="h-8 rounded-lg border border-[#D5D9D9] bg-white text-black hover:bg-[#f7fafa]"
                data-testid="shop-pagination-prev-button"
              >
                Trước
              </Button>
              <Button
                type="button"
                onClick={() => setOffset((current) => current + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="h-8 rounded-lg border border-[#D5D9D9] bg-white text-black hover:bg-[#f7fafa]"
                data-testid="shop-pagination-next-button"
              >
                Tiếp
              </Button>
            </div>
          </>
        )}
      </section>
    </div>
  );
};
