const http = require("http");

const PORT = parseInt(process.env.SERVICE_PORT || "8080", 10);

const NOTES = [
  { id: 1, title: "First note", body: "Hello from Node.js plugin" },
  { id: 2, title: "Second note", body: "Language-agnostic bridge works" },
];

const OPENAPI = {
  openapi: "3.1.0",
  info: { title: "Demo Node Plugin", version: "1.0.0" },
  paths: {
    "/health": {
      get: {
        summary: "Health",
        operationId: "health",
        responses: { 200: { description: "OK" } },
      },
    },
    "/notes": {
      get: {
        summary: "List Notes",
        operationId: "list_notes",
        responses: {
          200: {
            description: "OK",
            content: {
              "application/json": {
                schema: {
                  type: "array",
                  items: { $ref: "#/components/schemas/Note" },
                },
              },
            },
          },
        },
      },
    },
    "/info": {
      get: {
        summary: "Plugin Info",
        operationId: "info",
        responses: { 200: { description: "OK" } },
      },
    },
  },
  components: {
    schemas: {
      Note: {
        type: "object",
        required: ["id", "title", "body"],
        properties: {
          id: { type: "integer" },
          title: { type: "string" },
          body: { type: "string" },
        },
      },
    },
  },
};

function jsonResponse(res, code, data) {
  const body = JSON.stringify(data);
  res.writeHead(code, {
    "content-type": "application/json",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const path = req.url.split("?")[0];

  if (req.method === "GET" && path === "/health") {
    jsonResponse(res, 200, { status: "ok" });
  } else if (req.method === "GET" && path === "/notes") {
    jsonResponse(res, 200, NOTES);
  } else if (req.method === "GET" && path === "/info") {
    jsonResponse(res, 200, {
      plugin: "demo_node",
      version: "1.0.0",
      runtime: "node",
      description: "Node.js HTTP plugin proving language-agnostic contract",
    });
  } else if (req.method === "GET" && path === "/openapi.json") {
    jsonResponse(res, 200, OPENAPI);
  } else {
    jsonResponse(res, 404, { detail: "not found" });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`demo_node listening on 127.0.0.1:${PORT}`);
});
