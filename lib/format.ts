export const formatMoney = (cents: number | null) =>
  cents === null
    ? "Custom quote"
    : new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        maximumFractionDigits: 0,
      }).format(cents / 100);
