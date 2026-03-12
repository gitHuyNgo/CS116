import "@/App.css";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { AmazonLayout } from "@/components/layout/AmazonLayout";
import { ProductDetailPage } from "@/components/product/ProductDetailPage";
import { ShopPage } from "@/components/shop/ShopPage";

const STARTING_ITEM_ID = "000804000046";

function AppContent() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedItemId = searchParams.get("item_id");
  const pageView = searchParams.get("view");
  const initialQuery = searchParams.get("q") || "";

  useEffect(() => {
    if (!selectedItemId && !pageView) {
      setSearchParams({ view: "shop" }, { replace: true });
    }
  }, [selectedItemId, pageView, setSearchParams]);

  const showDetailPage = Boolean(selectedItemId);

  const handleItemSelect = (itemId) => {
    setSearchParams({ item_id: itemId });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleOpenShop = () => {
    setSearchParams({ view: "shop" });
  };

  const handleGlobalSearch = (term) => {
    const nextParams = { view: "shop" };
    if (term.trim()) {
      nextParams.q = term.trim();
    }
    setSearchParams(nextParams);
  };

  return (
    <AmazonLayout
      onOpenShop={handleOpenShop}
      onGlobalSearch={handleGlobalSearch}
    >
      {showDetailPage ? (
        <ProductDetailPage
          itemId={selectedItemId || STARTING_ITEM_ID}
          onBackToShop={handleOpenShop}
          onOpenItem={handleItemSelect}
        />
      ) : (
        <ShopPage initialQuery={initialQuery} onOpenItem={handleItemSelect} />
      )}
    </AmazonLayout>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<AppContent />} />
      </Routes>
    </BrowserRouter>
  );
}
