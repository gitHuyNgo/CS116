import { useState } from "react";
import { Menu, Search, ShoppingCart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const AmazonLayout = ({ onOpenShop, onGlobalSearch, children }) => {
  const [searchTerm, setSearchTerm] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    onGlobalSearch(searchTerm);
  };

  return (
    <div className="min-h-screen bg-[#f3f3f3] text-[#0F1111] text-[13px]" data-testid="app-shell">
      <header className="bg-[#131921] text-white" data-testid="main-nav">
        <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-3 py-2 sm:px-4">
          <button
            type="button"
            className="flex items-center gap-2 border border-transparent px-2 py-1 hover:border-white"
            onClick={onOpenShop}
            data-testid="amazon-logo-button"
          >
            <span className="text-lg font-bold leading-none">amazon</span>
            <span className="mt-1 text-[11px]">.com.vn</span>
          </button>

          <form
            onSubmit={handleSubmit}
            className="flex flex-1 items-center"
            data-testid="global-search-form"
          >
            <Input
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.target.value)}
              placeholder="Tìm kiếm sản phẩm"
              className="h-9 rounded-l-md rounded-r-none border-0 bg-white text-[13px] text-black focus-visible:ring-2 focus-visible:ring-[#E77600]"
              data-testid="global-search-input"
            />
            <Button
              type="submit"
              className="h-9 rounded-l-none rounded-r-md bg-[#febd69] px-3 text-black hover:bg-[#f3a847]"
              data-testid="global-search-submit-button"
            >
              <Search className="h-4 w-4" />
            </Button>
          </form>

          <Button
            type="button"
            variant="ghost"
            className="h-9 rounded-none border border-transparent px-2 text-white hover:border-white hover:bg-transparent"
            data-testid="header-cart-button"
          >
            <ShoppingCart className="mr-1 h-4 w-4" /> Giỏ hàng
          </Button>
        </div>
      </header>

      <div className="bg-[#232f3e] text-white" data-testid="sub-nav">
        <div className="mx-auto flex max-w-[1400px] items-center gap-2 px-3 py-2 sm:px-4">
          <Button
            type="button"
            variant="ghost"
            className="h-8 rounded-none border border-transparent px-2 text-white hover:border-white hover:bg-transparent"
            onClick={onOpenShop}
            data-testid="sub-nav-shop-button"
          >
            <Menu className="mr-1 h-4 w-4" /> Shop
          </Button>
        </div>
      </div>

      <main className="mx-auto w-full max-w-[1400px] px-3 py-4 sm:px-4" data-testid="page-content">
        {children}
      </main>
    </div>
  );
};
