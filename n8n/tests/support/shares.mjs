// The share of each value in a list: shares(list)(value).
export const shares = (values) => {
  const counts = {};
  for (const value of values) {
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return (key) => (counts[key] ?? 0) / values.length;
};

export const normalized = (weights) => {
  const total = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
  return Object.fromEntries(Object.entries(weights).map(([key, weight]) => [key, weight / total]));
};
