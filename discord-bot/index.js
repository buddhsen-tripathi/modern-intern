import { Chat } from "chat";
import { createDiscordAdapter } from "@chat-adapter/discord";
import { createMemoryState } from "@chat-adapter/state-memory";
import { createServer } from "http";

const NOTIFY_PORT = parseInt(process.env.DISCORD_NOTIFY_PORT || "3100", 10);
const CHANNEL_ID = process.env.DISCORD_CHANNEL_ID || "";

if (!CHANNEL_ID) {
  console.error("DISCORD_CHANNEL_ID is required (format: discord:{guildId}:{channelId})");
  process.exit(1);
}

const bot = new Chat({
  userName: process.env.BOT_USERNAME || "silas",
  adapters: {
    discord: createDiscordAdapter(),
  },
  state: createMemoryState(),
});

// Log when ready
bot.onNewMention(async (thread, message) => {
  await thread.post("I'm Silas, a voice assistant. I post updates here from voice sessions.");
});

// HTTP server to receive notifications from Python backend
const server = createServer(async (req, res) => {
  if (req.method === "POST" && req.url === "/notify") {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", async () => {
      try {
        const { action, message } = JSON.parse(body);
        if (!message) {
          res.writeHead(400, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "message required" }));
          return;
        }

        const channel = bot.channel(CHANNEL_ID);
        await channel.post({ markdown: message });

        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true }));
      } catch (err) {
        console.error("Notify error:", err.message);
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: err.message }));
      }
    });
  } else {
    res.writeHead(404);
    res.end();
  }
});

server.listen(NOTIFY_PORT, () => {
  console.log(`Silas Discord bot notify server on :${NOTIFY_PORT}`);
  console.log(`Posting to channel: ${CHANNEL_ID}`);
});
