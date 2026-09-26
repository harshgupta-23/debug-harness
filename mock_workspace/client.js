/**
 * Frontend client module consuming the orders API.
 */

async function fetchOrderDetails(orderId) {
  try {
    const response = await fetch('/api/v1/orders/' + orderId);
    if (!response.ok) {
      throw new Error('Network error fetching order');
    }
    const orderData = await response.json();
    return orderData;
  } catch (err) {
    console.error('Failed to load order', err);
    return null;
  }
}

module.exports = { fetchOrderDetails };
