import assert from "node:assert/strict";
import test from "node:test";
import { buyerVisibleBody, deliveryAllowsSend } from "./inbound-item.ts";

test("default delivery does not send", () => {
  assert.equal(deliveryAllowsSend(undefined), false);
  assert.equal(deliveryAllowsSend({}), false);
  assert.equal(deliveryAllowsSend({ delivery: "preview" }), false);
  assert.equal(deliveryAllowsSend({ delivery: "send" }), true);
});

test("buyer body keeps the trusted item id", () => {
  const known = buyerVisibleBody({
    content: "多少钱",
    itemId: "sim-preview-001",
    itemKnown: true,
  });
  assert.match(known, /itemId=sim-preview-001/);
  assert.match(known, /多少钱/);

  const unknown = buyerVisibleBody({
    content: "多少钱",
    itemId: "900000000001",
    itemKnown: false,
    needsHuman: true,
  });
  assert.match(unknown, /未确认/);
  assert.match(unknown, /需要人工/);
  assert.doesNotMatch(unknown, /标价/);
});
