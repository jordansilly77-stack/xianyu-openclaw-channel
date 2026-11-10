/** 入站商品上下文。默认预览，不向买家发送。 */

export function deliveryAllowsSend(config: { delivery?: string } | null | undefined): boolean {
  return config?.delivery === "send";
}

export function buyerVisibleBody(data: {
  content?: string;
  itemId?: string | null;
  itemKnown?: boolean;
  needsHuman?: boolean;
}): string {
  const itemId = data.itemId ? String(data.itemId) : "";
  const known = data.itemKnown === true && itemId.length > 0;
  const header = known
    ? `[当前商品] itemId=${itemId}`
    : `[当前商品] 未确认${itemId ? ` itemId=${itemId}` : ""}，需要人工，不能编造商品事实`;
  return `${header}\n买家原文：${data.content ?? ""}`;
}
