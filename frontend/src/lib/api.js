import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const client = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  timeout: 15000,
});

export const fetchCatalog = async (params) => {
  const response = await client.get("/items", { params });
  return response.data;
};

export const fetchFilterMeta = async () => {
  const response = await client.get("/items/meta");
  return response.data;
};

export const fetchItemById = async (itemId) => {
  const response = await client.get(`/items/${itemId}`);
  return response.data;
};

export const fetchRecommendations = async (itemId) => {
  const response = await client.get(`/recommendations/${itemId}`);
  return response.data;
};

export const fetchSearchRecommendations = async (query) => {
  const response = await client.get("/search-recommendations", {
    params: { q: query },
  });
  return response.data;
};
