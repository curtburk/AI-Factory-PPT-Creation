#!/usr/bin/env node
/**
 * NemoClaw Deck Factory -- Deterministic Renderer
 * =================================================
 * Takes a JSON deck plan and produces a .pptx file using pptxgenjs.
 * No LLM calls. No randomness. Same input always produces same output.
 *
 * Usage:
 *   node render_deck.js <input.json> <output.pptx>
 */

const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// ── Palettes ─────────────────────────────────────────────────────────────────

const PALETTES = {
  midnight_executive: {
    primary: "1E2761",
    secondary: "CADCFC",
    accent: "FFFFFF",
    darkBg: "1E2761",
    lightBg: "FFFFFF",
    darkText: "1E2761",
    lightText: "FFFFFF",
    mutedText: "8899BB",
    chartColors: ["CADCFC", "5A72B5", "8EAADB", "1E2761"],
  },
  forest_moss: {
    primary: "2C5F2D",
    secondary: "97BC62",
    accent: "F5F5F5",
    darkBg: "2C5F2D",
    lightBg: "F5F5F5",
    darkText: "2C5F2D",
    lightText: "FFFFFF",
    mutedText: "6B8F6C",
    chartColors: ["97BC62", "2C5F2D", "C4D9A0", "4A7C4B"],
  },
  coral_energy: {
    primary: "F96167",
    secondary: "F9E795",
    accent: "2F3C7E",
    darkBg: "2F3C7E",
    lightBg: "FFFFFF",
    darkText: "2F3C7E",
    lightText: "FFFFFF",
    mutedText: "7A82A6",
    chartColors: ["F96167", "F9E795", "2F3C7E", "FB9DA0"],
  },
  warm_terracotta: {
    primary: "B85042",
    secondary: "E7E8D1",
    accent: "A7BEAE",
    darkBg: "B85042",
    lightBg: "F5F3E8",
    darkText: "3D2017",
    lightText: "FFFFFF",
    mutedText: "8C7B75",
    chartColors: ["B85042", "A7BEAE", "E7E8D1", "D4776B"],
  },
  ocean_gradient: {
    primary: "065A82",
    secondary: "1C7293",
    accent: "21295C",
    darkBg: "21295C",
    lightBg: "F0F5F8",
    darkText: "21295C",
    lightText: "FFFFFF",
    mutedText: "5A7A8C",
    chartColors: ["065A82", "1C7293", "21295C", "3A9CC4"],
  },
  charcoal_minimal: {
    primary: "36454F",
    secondary: "F2F2F2",
    accent: "212121",
    darkBg: "212121",
    lightBg: "FFFFFF",
    darkText: "212121",
    lightText: "FFFFFF",
    mutedText: "888888",
    chartColors: ["36454F", "888888", "BBBBBB", "212121"],
  },
  teal_trust: {
    primary: "028090",
    secondary: "00A896",
    accent: "02C39A",
    darkBg: "02535E",
    lightBg: "F0FAFA",
    darkText: "02535E",
    lightText: "FFFFFF",
    mutedText: "5A9EA5",
    chartColors: ["028090", "00A896", "02C39A", "015F6B"],
  },
};

// ── Icon Mapping ─────────────────────────────────────────────────────────────

const ICON_MAP = {
  shield: () => require("react-icons/hi").HiShieldCheck,
  server: () => require("react-icons/hi").HiServer,
  zap: () => require("react-icons/hi").HiLightningBolt,
  chart: () => require("react-icons/hi").HiChartBar,
  users: () => require("react-icons/hi").HiUserGroup,
  lock: () => require("react-icons/hi").HiLockClosed,
  globe: () => require("react-icons/hi").HiGlobe,
  check: () => require("react-icons/hi").HiCheckCircle,
  target: () => require("react-icons/hi").HiCursorClick,
  layers: () => require("react-icons/hi").HiCollection,
};

async function iconToBase64Png(iconName, color, size = 256) {
  const loader = ICON_MAP[iconName];
  if (!loader) {
    // Return a colored circle as fallback
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><circle cx="${size/2}" cy="${size/2}" r="${size/2 - 10}" fill="#${color}"/></svg>`;
    const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
    return "image/png;base64," + pngBuffer.toString("base64");
  }
  const IconComponent = loader();
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color: `#${color}`, size: String(size) })
  );
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// ── Layout Renderers ─────────────────────────────────────────────────────────

function renderTitleSlide(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.darkBg };

  // Determine if background is light or dark to pick readable text color
  const bgHex = palette.darkBg || "000000";
  const r = parseInt(bgHex.substring(0, 2), 16);
  const g = parseInt(bgHex.substring(2, 4), 16);
  const b = parseInt(bgHex.substring(4, 6), 16);
  const brightness = (r * 299 + g * 587 + b * 114) / 1000;
  const titleColor = brightness > 128 ? palette.darkText : palette.lightText;
  const subtitleColor = brightness > 128 ? palette.primary : palette.secondary;
  const authorColor = brightness > 128 ? palette.mutedText : palette.mutedText;
  const accentBarColor = brightness > 128 ? palette.primary : palette.secondary;

  // Title
  slide.addText(slideData.title || "Untitled", {
    x: 0.8, y: 1.5, w: 8.4, h: 1.5,
    fontSize: 44, fontFace: fonts.header, color: titleColor,
    bold: true, align: "left", valign: "middle", margin: 0,
  });

  // Subtitle
  if (slideData.subtitle) {
    slide.addText(slideData.subtitle, {
      x: 0.8, y: 3.1, w: 8.4, h: 0.8,
      fontSize: 20, fontFace: fonts.body, color: subtitleColor,
      align: "left", valign: "top", margin: 0,
    });
  }

  // Author from meta
  const author = slideData._meta?.author;
  if (author) {
    slide.addText(author, {
      x: 0.8, y: 4.8, w: 4, h: 0.4,
      fontSize: 12, fontFace: fonts.body, color: authorColor,
      align: "left", margin: 0,
    });
  }

  // Accent bar at top
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: accentBarColor },
  });
}

function renderSectionDivider(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.primary };

  slide.addText(slideData.title || "Section", {
    x: 0.8, y: 1.8, w: 8.4, h: 2.0,
    fontSize: 40, fontFace: fonts.header, color: palette.lightText,
    bold: true, align: "left", valign: "middle", margin: 0,
  });

  // Thin accent line below title
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.9, w: 2.5, h: 0.04,
    fill: { color: palette.secondary },
  });
}

function renderBullets(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  // Left accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.3, w: 0.06, h: 3.5,
    fill: { color: palette.primary },
  });

  // Bullets
  const items = slideData.items || [];
  const textItems = items.map((item, i) => ({
    text: item,
    options: {
      bullet: true,
      breakLine: i < items.length - 1,
      fontSize: 16,
      color: palette.darkText,
      paraSpaceAfter: 8,
    },
  }));

  slide.addText(textItems, {
    x: 1.1, y: 1.3, w: 8.1, h: 3.5,
    fontFace: fonts.body, valign: "top", margin: 0,
  });

  // Speaker notes
  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

function renderTwoColumn(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  const left = slideData.left || {};
  const right = slideData.right || {};

  // Left column background card
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.3, w: 4.2, h: 3.8,
    fill: { color: "FFFFFF" },
    shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.08 },
  });

  // Left column heading
  if (left.heading) {
    slide.addText(left.heading, {
      x: 0.8, y: 1.5, w: 3.6, h: 0.5,
      fontSize: 18, fontFace: fonts.header, color: palette.primary,
      bold: true, align: "left", margin: 0,
    });
  }

  // Left column items
  const leftItems = (left.items || []).map((item, i, arr) => ({
    text: item,
    options: {
      bullet: true,
      breakLine: i < arr.length - 1,
      fontSize: 14,
      color: palette.darkText,
      paraSpaceAfter: 6,
    },
  }));
  slide.addText(leftItems, {
    x: 0.8, y: 2.1, w: 3.6, h: 2.8,
    fontFace: fonts.body, valign: "top", margin: 0,
  });

  // Right column background card
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.3, y: 1.3, w: 4.2, h: 3.8,
    fill: { color: "FFFFFF" },
    shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.08 },
  });

  // Right column heading
  if (right.heading) {
    slide.addText(right.heading, {
      x: 5.6, y: 1.5, w: 3.6, h: 0.5,
      fontSize: 18, fontFace: fonts.header, color: palette.primary,
      bold: true, align: "left", margin: 0,
    });
  }

  // Right column items
  const rightItems = (right.items || []).map((item, i, arr) => ({
    text: item,
    options: {
      bullet: true,
      breakLine: i < arr.length - 1,
      fontSize: 14,
      color: palette.darkText,
      paraSpaceAfter: 6,
    },
  }));
  slide.addText(rightItems, {
    x: 5.6, y: 2.1, w: 3.6, h: 2.8,
    fontFace: fonts.body, valign: "top", margin: 0,
  });

  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

function renderStatCallout(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  const stats = slideData.stats || [];
  const count = Math.min(stats.length, 4);
  const cardWidth = (8.4 - (count - 1) * 0.3) / count;
  const startX = 0.8;

  stats.slice(0, 4).forEach((stat, i) => {
    const x = startX + i * (cardWidth + 0.3);

    // Card background
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.5, w: cardWidth, h: 3.2,
      fill: { color: "FFFFFF" },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.08 },
    });

    // Top accent bar
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.5, w: cardWidth, h: 0.06,
      fill: { color: palette.primary },
    });

    // Stat value
    slide.addText(stat.value || "0", {
      x: x, y: 1.9, w: cardWidth, h: 1.4,
      fontSize: 52, fontFace: fonts.header, color: palette.primary,
      bold: true, align: "center", valign: "middle", margin: 0,
    });

    // Stat label
    slide.addText(stat.label || "", {
      x: x + 0.2, y: 3.5, w: cardWidth - 0.4, h: 0.8,
      fontSize: 13, fontFace: fonts.body, color: palette.mutedText,
      align: "center", valign: "top", margin: 0,
    });
  });

  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

function renderChartSlide(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  const chart = slideData.chart || {};
  const chartType = (chart.type || "bar").toLowerCase();
  const labels = chart.labels || [];
  const series = chart.series || [];

  // Map chart type string to pptxgenjs chart enum
  const typeMap = {
    bar: pres.charts.BAR,
    line: pres.charts.LINE,
    pie: pres.charts.PIE,
    doughnut: pres.charts.DOUGHNUT,
    area: pres.charts.AREA,
  };
  const pptxChartType = typeMap[chartType] || pres.charts.BAR;

  const chartData = series.map((s) => ({
    name: s.name || "Series",
    labels: labels,
    values: s.values || [],
  }));

  const isPie = chartType === "pie" || chartType === "doughnut";

  const chartOpts = {
    x: 0.8, y: 1.3, w: 8.4, h: 3.8,
    chartColors: palette.chartColors,
    chartArea: { fill: { color: palette.lightBg }, roundedCorners: true },
    catAxisLabelColor: palette.mutedText,
    valAxisLabelColor: palette.mutedText,
    valGridLine: { color: "E2E8F0", size: 0.5 },
    catGridLine: { style: "none" },
    showLegend: series.length > 1 || isPie,
    legendPos: "b",
    legendFontSize: 10,
    legendColor: palette.mutedText,
  };

  if (chartType === "bar") {
    chartOpts.barDir = "col";
    chartOpts.showValue = true;
    chartOpts.dataLabelPosition = "outEnd";
    chartOpts.dataLabelColor = palette.darkText;
    chartOpts.dataLabelFontSize = 10;
  }

  if (isPie) {
    chartOpts.showPercent = true;
  }

  if (chartType === "line") {
    chartOpts.lineSize = 3;
    chartOpts.lineSmooth = true;
  }

  slide.addChart(pptxChartType, chartData, chartOpts);

  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

async function renderIconGrid(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  const items = slideData.items || [];
  const count = Math.min(items.length, 6);

  // Determine grid: 2 or 3 columns
  const cols = count <= 4 ? 2 : 3;
  const rows = Math.ceil(count / cols);

  const gridW = 8.4;
  const gridH = 3.6;
  const startX = 0.8;
  const startY = 1.4;
  const cellW = (gridW - (cols - 1) * 0.3) / cols;
  const cellH = (gridH - (rows - 1) * 0.2) / rows;

  for (let idx = 0; idx < count; idx++) {
    const item = items[idx];
    const col = idx % cols;
    const row = Math.floor(idx / cols);
    const x = startX + col * (cellW + 0.3);
    const y = startY + row * (cellH + 0.2);

    // Card background
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: y, w: cellW, h: cellH,
      fill: { color: "FFFFFF" },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1, angle: 135, opacity: 0.08 },
    });

    // Icon circle background
    const circleSize = 0.55;
    const circleX = x + 0.3;
    const circleY = y + 0.25;
    slide.addShape(pres.shapes.OVAL, {
      x: circleX, y: circleY, w: circleSize, h: circleSize,
      fill: { color: palette.primary },
    });

    // Icon
    const iconData = await iconToBase64Png(item.icon || "check", palette.lightText, 256);
    const iconPad = 0.12;
    slide.addImage({
      data: iconData,
      x: circleX + iconPad, y: circleY + iconPad,
      w: circleSize - iconPad * 2, h: circleSize - iconPad * 2,
    });

    // Item title
    slide.addText(item.title || "", {
      x: circleX + circleSize + 0.15, y: circleY - 0.05,
      w: cellW - circleSize - 0.75, h: 0.35,
      fontSize: 15, fontFace: fonts.header, color: palette.darkText,
      bold: true, align: "left", valign: "middle", margin: 0,
    });

    // Item description
    if (item.description) {
      slide.addText(item.description, {
        x: circleX + circleSize + 0.15, y: circleY + 0.3,
        w: cellW - circleSize - 0.75, h: 0.4,
        fontSize: 11, fontFace: fonts.body, color: palette.mutedText,
        align: "left", valign: "top", margin: 0,
      });
    }
  }

  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

function renderImageText(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.lightBg };

  // Title
  slide.addText(slideData.title || "", {
    x: 0.8, y: 0.4, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: fonts.header, color: palette.darkText,
    bold: true, align: "left", margin: 0,
  });

  const imageOnLeft = (slideData.imagePosition || "left") === "left";
  const imgX = imageOnLeft ? 0.5 : 5.2;
  const txtX = imageOnLeft ? 5.2 : 0.8;

  // Image placeholder (colored rectangle with label)
  slide.addShape(pres.shapes.RECTANGLE, {
    x: imgX, y: 1.3, w: 4.3, h: 3.8,
    fill: { color: palette.primary },
  });
  slide.addText(slideData.imagePlaceholder || "[Image]", {
    x: imgX, y: 1.3, w: 4.3, h: 3.8,
    fontSize: 14, fontFace: fonts.body, color: palette.lightText,
    align: "center", valign: "middle", margin: 0,
    italic: true,
  });

  // Text content
  if (slideData.text) {
    slide.addText(slideData.text, {
      x: txtX, y: 1.3, w: 4.0, h: 3.8,
      fontSize: 15, fontFace: fonts.body, color: palette.darkText,
      align: "left", valign: "top", margin: 0,
      lineSpacingMultiple: 1.3,
    });
  }

  if (slideData.speakerNotes) {
    slide.addNotes(slideData.speakerNotes);
  }
}

function renderClosing(pres, slide, slideData, palette, fonts) {
  slide.background = { color: palette.darkBg };

  // Detect brightness for adaptive text colors
  const bgHex = palette.darkBg || "000000";
  const r = parseInt(bgHex.substring(0, 2), 16);
  const g = parseInt(bgHex.substring(2, 4), 16);
  const b = parseInt(bgHex.substring(4, 6), 16);
  const brightness = (r * 299 + g * 587 + b * 114) / 1000;
  const titleColor = brightness > 128 ? palette.darkText : palette.lightText;
  const subtitleColor = brightness > 128 ? palette.primary : palette.secondary;
  const contactColor = brightness > 128 ? palette.mutedText : palette.mutedText;
  const accentColor = brightness > 128 ? palette.primary : palette.secondary;

  // Accent bar at bottom
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.565, w: 10, h: 0.06,
    fill: { color: accentColor },
  });

  // Title
  slide.addText(slideData.title || "Thank You", {
    x: 0.8, y: 1.5, w: 8.4, h: 1.5,
    fontSize: 44, fontFace: fonts.header, color: titleColor,
    bold: true, align: "left", valign: "middle", margin: 0,
  });

  // Subtitle
  if (slideData.subtitle) {
    slide.addText(slideData.subtitle, {
      x: 0.8, y: 3.1, w: 8.4, h: 0.6,
      fontSize: 22, fontFace: fonts.body, color: subtitleColor,
      align: "left", margin: 0,
    });
  }

  // Contact info
  if (slideData.contactInfo) {
    slide.addText(slideData.contactInfo, {
      x: 0.8, y: 4.5, w: 4, h: 0.4,
      fontSize: 14, fontFace: fonts.body, color: contactColor,
      align: "left", margin: 0,
    });
  }
}

// ── Brand Config ─────────────────────────────────────────────────────────────

/**
 * Load brand.json from the same directory as this script.
 * Returns { colors: {...}, fonts: {...} } or empty objects if not found.
 */
function loadBrandConfig() {
  const brandPath = path.join(__dirname, "brand.json");
  try {
    const raw = fs.readFileSync(brandPath, "utf8");
    const config = JSON.parse(raw);
    return {
      colors: config.colors || {},
      fonts: config.fonts || {},
    };
  } catch (e) {
    // No brand config or invalid JSON -- that's fine, use palette defaults
    return { colors: {}, fonts: {} };
  }
}

/**
 * Resolve colors with three-tier precedence:
 *   1. Per-slide "colors" override (highest priority)
 *   2. Brand config (brand.json)
 *   3. Built-in palette (lowest priority)
 *
 * Every color role has a defined fallback chain so nothing is ever undefined.
 */
function resolveColors(palette, brandColors, slideColors) {
  const resolve = (key) => {
    // Slide override wins
    if (slideColors && slideColors[key]) return slideColors[key];
    // Brand config next
    if (brandColors && brandColors[key]) return brandColors[key];
    // Palette default
    return palette[key];
  };

  // chartColors needs special handling (array merge)
  let chartColors = palette.chartColors;
  if (brandColors && brandColors.chartColors) chartColors = brandColors.chartColors;
  if (slideColors && slideColors.chartColors) chartColors = slideColors.chartColors;

  return {
    primary: resolve("primary"),
    secondary: resolve("secondary"),
    accent: resolve("accent"),
    darkBg: resolve("darkBg"),
    lightBg: resolve("lightBg"),
    darkText: resolve("darkText"),
    lightText: resolve("lightText"),
    mutedText: resolve("mutedText"),
    highlight: resolve("highlight") || resolve("accent"),
    chartColors: chartColors,
  };
}

// ── Main Render Function ─────────────────────────────────────────────────────

async function renderDeck(inputPath, outputPath) {
  const raw = fs.readFileSync(inputPath, "utf8");
  let deckPlan;
  try {
    deckPlan = JSON.parse(raw);
  } catch (e) {
    console.error("ERROR: Invalid JSON input:", e.message);
    process.exit(1);
  }

  const meta = deckPlan.meta || {};
  const slides = deckPlan.slides || [];

  if (slides.length === 0) {
    console.error("ERROR: No slides in deck plan");
    process.exit(1);
  }

  // Load brand config
  const brand = loadBrandConfig();
  const hasBrand = Object.keys(brand.colors).length > 0;
  if (hasBrand) {
    console.log("BRAND: Loaded brand.json color overrides");
  }

  // Resolve base palette (used as lowest-priority fallback)
  const paletteName = meta.palette || "midnight_executive";
  const basePalette = PALETTES[paletteName] || PALETTES.midnight_executive;

  // Resolve fonts: brand.json > meta > defaults
  const fonts = {
    header: brand.fonts.headerFont || meta.headerFont || "Georgia",
    body: brand.fonts.bodyFont || meta.bodyFont || "Calibri",
  };

  // Create presentation
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = meta.author || "NemoClaw Deck Factory";
  pres.title = meta.title || "Presentation";

  // Render each slide
  const layoutRenderers = {
    title_slide: renderTitleSlide,
    section_divider: renderSectionDivider,
    bullets: renderBullets,
    two_column: renderTwoColumn,
    stat_callout: renderStatCallout,
    chart_slide: renderChartSlide,
    icon_grid: renderIconGrid,
    image_text: renderImageText,
    closing: renderClosing,
  };

  for (const slideData of slides) {
    const layout = slideData.layout || "bullets";
    const renderer = layoutRenderers[layout];

    if (!renderer) {
      console.warn(`WARNING: Unknown layout "${layout}", falling back to bullets`);
    }

    const slide = pres.addSlide();
    const fn = renderer || renderBullets;

    // Inject meta into slide data so renderers can access author etc.
    slideData._meta = meta;

    // Resolve colors for this slide: slide.colors > brand > palette
    const palette = resolveColors(basePalette, brand.colors, slideData.colors);

    // Some renderers are async (icon_grid)
    await fn(pres, slide, slideData, palette, fonts);

    // Stamp logo on every slide if one exists
    const logoPath = path.join(__dirname, "logos", "current_logo.png");
    if (fs.existsSync(logoPath)) {
      // Read image dimensions to preserve aspect ratio
      let logoW = 0.6;
      let logoH = 0.6;
      try {
        const metadata = await sharp(logoPath).metadata();
        if (metadata.width && metadata.height) {
          const aspect = metadata.width / metadata.height;
          const maxDim = 0.6; // inches
          if (aspect >= 1) {
            // Wider than tall
            logoW = maxDim;
            logoH = maxDim / aspect;
          } else {
            // Taller than wide
            logoH = maxDim;
            logoW = maxDim * aspect;
          }
        }
      } catch (e) {
        // Fallback to square if metadata read fails
      }

      slide.addImage({
        path: logoPath,
        x: 10 - logoW - 0.2,
        y: 5.625 - logoH - 0.15,
        w: logoW,
        h: logoH,
      });
    }
  }

  // Write file
  await pres.writeFile({ fileName: outputPath });
  console.log(`OK: ${slides.length} slides rendered to ${outputPath}`);
}

// ── CLI Entry ────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);
if (args.length < 2) {
  console.error("Usage: node render_deck.js <input.json> <output.pptx>");
  process.exit(1);
}

renderDeck(args[0], args[1]).catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});