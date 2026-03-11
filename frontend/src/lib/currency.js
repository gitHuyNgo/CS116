const vndFormatter = new Intl.NumberFormat("vi-VN", {
  style: "currency",
  currency: "VND",
  maximumFractionDigits: 0,
});

export const formatVnd = (value) => {
  const numericValue = Number(value) || 0;
  return vndFormatter.format(numericValue);
};
