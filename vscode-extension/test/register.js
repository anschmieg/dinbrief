const Module = require("node:module");
const vscode = require("./vscode-stub.js");

const load = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "vscode") return vscode;
  return load.call(this, request, parent, isMain);
};
