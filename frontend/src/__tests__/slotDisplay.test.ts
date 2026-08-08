import { expect, test } from "vitest";
import { displaySlotName } from "../slotDisplay";

test("shows the Shopee main poster slot in Chinese", () => {
  expect(displaySlotName({ slot: "Shopee high-CTR main poster", name: "Shopee high-CTR main poster", slotOrder: 1 })).toBe("主图");
});
