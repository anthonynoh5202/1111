import { pdf } from "pdf-to-img";
import fs from "fs";
const doc = await pdf("report.pdf", { scale: 2 });
let i = 1;
for await (const page of doc) { fs.writeFileSync("page" + i + ".png", page); i++; }
console.log("pages", i - 1);
