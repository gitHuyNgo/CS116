import { useEffect, useMemo, useState } from "react";
import { ImageOff, Loader2, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchItemById, fetchRecommendations } from "@/lib/api";
import { formatVnd } from "@/lib/currency";

const RecommendationRow = ({ title, items, sectionId, onOpenItem }) => (
  <section className="space-y-2 border border-[#e7e7e7] bg-white p-3" data-testid={`${sectionId}-section`}>
    <h2 className="text-base font-bold" data-testid={`${sectionId}-title`}>
      {title}
    </h2>
    {items.length === 0 ? (
      <p className="text-xs text-[#565959]" data-testid={`${sectionId}-empty`}>
        Chưa có sản phẩm gợi ý.
      </p>
    ) : (
      <div className="amazon-scrollbar flex gap-3 overflow-x-auto pb-2" data-testid={`${sectionId}-list`}>
        {items.map((item) => (
          <button
            key={`${sectionId}-${item.item_id}`}
            type="button"
            onClick={() => onOpenItem(item.item_id)}
            className="w-[180px] flex-shrink-0 border border-[#e7e7e7] bg-white p-2 text-left hover:bg-[#f9f9f9]"
            data-testid={`${sectionId}-item-${item.item_id}`}
          >
            <div className="mb-2 h-24 bg-[#f1f3f3]" data-testid={`${sectionId}-item-image-${item.item_id}`}>
              <div className="flex h-full items-center justify-center text-[#9ca3af]">
                <ImageOff className="h-5 w-5" />
              </div>
            </div>
            <p className="line-clamp-2 min-h-[34px] text-[13px] font-medium" data-testid={`${sectionId}-item-name-${item.item_id}`}>
              {item.name}
            </p>
            <p className="mt-1 text-xs text-[#007185]" data-testid={`${sectionId}-item-brand-${item.item_id}`}>
              {item.brand}
            </p>
            <p className="mt-1 text-sm font-bold text-[#B12704]" data-testid={`${sectionId}-item-price-${item.item_id}`}>
              {formatVnd(item.price)}
            </p>
          </button>
        ))}
      </div>
    )}
  </section>
);

export const ProductDetailPage = ({ itemId, onBackToShop, onOpenItem }) => {
  const [item, setItem] = useState(null);
  const [recommendations, setRecommendations] = useState({
    frequently_bought_together: [],
    relevant: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const loadProductData = async () => {
      setLoading(true);
      setError("");
      try {
        const [productResponse, recommendationResponse] = await Promise.all([
          fetchItemById(itemId),
          fetchRecommendations(itemId),
        ]);
        setItem(productResponse);
        setRecommendations({
          frequently_bought_together: recommendationResponse.frequently_bought_together || [],
          relevant: recommendationResponse.relevant || [],
        });
      } catch (fetchError) {
        const message = fetchError?.response?.data?.detail || "Không thể tải thông tin sản phẩm.";
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadProductData();
  }, [itemId]);

  const ratingValue = useMemo(() => Number(item?.rating || 4.2), [item]);

  if (loading) {
    return (
      <div className="flex min-h-[260px] items-center justify-center border border-[#e7e7e7] bg-white" data-testid="product-detail-loading-state">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        Đang tải chi tiết sản phẩm...
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="space-y-4 border border-[#e7e7e7] bg-white p-4" data-testid="product-detail-error-state">
        <p className="text-sm text-[#B12704]" data-testid="product-detail-error-message">
          {error || "Không tìm thấy sản phẩm"}
        </p>
        <Button
          type="button"
          onClick={onBackToShop}
          className="h-9 rounded-full bg-[#FFD814] px-4 text-black hover:bg-[#F7CA00]"
          data-testid="product-detail-back-to-shop-button"
        >
          Quay lại Shop
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="product-detail-page">
      <div className="border border-[#e7e7e7] bg-white p-4">
        <div className="grid grid-cols-1 gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]" data-testid="product-detail-main-layout">
          <div className="md:sticky md:top-4" data-testid="product-detail-image-column">
            <div className="aspect-square border border-[#e7e7e7] bg-[#f5f6f6]" data-testid="product-detail-image-placeholder">
              <div className="flex h-full flex-col items-center justify-center gap-2 text-[#6b7280]">
                <ImageOff className="h-10 w-10" />
                <p className="text-xs">No image available</p>
              </div>
            </div>
          </div>

          <div className="space-y-2" data-testid="product-detail-info-column">
            <h1 className="text-[24px] font-normal leading-7" data-testid="product-detail-title">
              {item.name}
            </h1>
            <p className="text-[13px]" data-testid="product-detail-brand">
              Thương hiệu: <span className="text-[#007185]">{item.brand}</span>
            </p>
            <div className="flex items-center gap-2" data-testid="product-detail-rating">
              <div className="flex items-center">
                {Array.from({ length: 5 }).map((_, index) => (
                  <Star
                    key={`star-${index}`}
                    className={`h-4 w-4 ${index < Math.round(ratingValue) ? "fill-[#FFA41C] text-[#FFA41C]" : "text-[#d1d5db]"}`}
                  />
                ))}
              </div>
              <span className="text-xs text-[#007185]">{ratingValue.toFixed(1)}</span>
            </div>
            <hr className="border-[#e7e7e7]" />
            <p className="text-[28px] leading-none text-[#B12704]" data-testid="product-detail-price">
              {formatVnd(item.price)}
            </p>
            <p className="text-xs text-[#565959]" data-testid="product-detail-category">
              Danh mục: {item.category_l1}
            </p>
            <p className="text-xs text-[#565959]" data-testid="product-detail-item-id">
              Mã sản phẩm: {item.item_id}
            </p>
            <div className="flex flex-wrap gap-2 pt-2">
              <Button
                type="button"
                className="h-9 rounded-full bg-[#FFD814] px-4 text-black hover:bg-[#F7CA00]"
                data-testid="product-detail-add-to-cart-button"
              >
                Add to Cart
              </Button>
              <Button
                type="button"
                onClick={onBackToShop}
                className="h-9 rounded-lg border border-[#D5D9D9] bg-white px-4 text-black hover:bg-[#f7fafa]"
                data-testid="product-detail-open-shop-button"
              >
                Quay lại Shop
              </Button>
            </div>
          </div>
        </div>
      </div>

      <RecommendationRow
        title="Frequently bought together"
        items={recommendations.frequently_bought_together}
        sectionId="frequently-bought"
        onOpenItem={onOpenItem}
      />

      <RecommendationRow
        title="Relevant alternatives"
        items={recommendations.relevant}
        sectionId="relevant-items"
        onOpenItem={onOpenItem}
      />
    </div>
  );
};
