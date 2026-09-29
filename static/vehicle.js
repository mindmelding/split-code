// Parametric side-elevation cutaways. Vehicles face left; all units are viewBox units.
(function () {
  const W = 1000;
  const H = 480;
  const GROUND = 392;

  // Upper outline runs nose-bottom → tail-bottom. The indexes name the cowl,
  // the top of the windshield, the end of the roof and the base of the rear glass.
  const BODIES = {
    sedan: {
      r: 46, fx: 235, rx: 745, sill: 342,
      pts: [[70, 338], [76, 300], [100, 285], [362, 262], [472, 176], [682, 178], [822, 250], [924, 258], [930, 338]],
      cowl: 3, ws: 4, roof: 5, rear: 6, pillars: [0.5], seats: [0.24, 0.52],
    },
    crossover: {
      r: 52, fx: 240, rx: 752, sill: 332,
      pts: [[68, 332], [74, 290], [100, 272], [346, 250], [456, 156], [816, 158], [902, 196], [924, 230], [928, 332]],
      cowl: 3, ws: 4, roof: 5, rear: 6, pillars: [0.42, 0.8], seats: [0.28, 0.6],
    },
    suv: {
      r: 58, fx: 236, rx: 762, sill: 320,
      pts: [[74, 322], [78, 250], [86, 238], [336, 230], [388, 136], [906, 136], [918, 146], [922, 322]],
      cowl: 3, ws: 4, roof: 5, rear: 6, pillars: [0.38, 0.72], seats: [0.3, 0.6],
    },
    pickup: {
      r: 58, fx: 226, rx: 772, sill: 320,
      pts: [[60, 322], [64, 248], [72, 238], [330, 228], [422, 140], [562, 140], [582, 150], [586, 232], [940, 232], [946, 322]],
      cowl: 3, ws: 4, roof: 5, rear: 6, pillars: [0.62], seats: [0.45], bed: true,
    },
    minivan: {
      r: 48, fx: 212, rx: 772, sill: 336,
      pts: [[64, 334], [72, 288], [108, 272], [262, 252], [304, 246], [424, 140], [862, 136], [918, 166], [928, 252], [930, 334]],
      cowl: 4, ws: 5, roof: 6, rear: 7, pillars: [0.3, 0.68], seats: [0.22, 0.48, 0.74],
    },
    fastback: {
      r: 50, fx: 236, rx: 752, sill: 336,
      pts: [[68, 334], [74, 296], [110, 282], [332, 262], [472, 168], [642, 160], [880, 232], [926, 254], [930, 334]],
      cowl: 3, ws: 4, roof: 5, rear: 6, pillars: [0.52], seats: [0.2, 0.55],
    },
  };

  const LABELS = {
    body: "Body shell",
    wheels: "Wheels & tires",
    brakes: "Brakes",
    suspension: "Suspension",
    steering: "Steering assist",
    engine: "Engine",
    motor: "Drive motors",
    transmission: "Transmission",
    driveline: "Driveline",
    battery12v: "12V battery",
    starter: "Starter",
    ecu: "Control module",
    fuel: "Fuel system",
    pack: "HV battery pack",
    exhaust: "Exhaust",
    cooling: "Cooling",
    harness: "Wiring harness",
    restraints: "Airbags & belts",
    seats: "Seats",
    lights: "Lighting",
    sensors: "Cameras & radar",
    wipers: "Wipers & glass",
    pedals: "Pedals & throttle",
    shifter: "Shifter",
    latches: "Latches",
    trim: "Exterior trim",
  };

  // Where each part travels when the drawing comes apart.
  const EXPLODE = {
    body: [0, -18], wheels: [0, 34], brakes: [0, 78], suspension: [0, -84],
    steering: [30, -128], engine: [-36, -96], motor: [0, -92], transmission: [36, 64],
    driveline: [0, 90], battery12v: [-70, -116], starter: [10, 62], ecu: [30, -150],
    fuel: [0, 72], pack: [0, 86], exhaust: [0, 100], cooling: [-86, -24],
    harness: [0, 118], restraints: [0, -170], seats: [0, -40], lights: [0, -70],
    sensors: [0, -150], wipers: [0, -120], pedals: [40, 50], shifter: [50, -70],
    latches: [0, -80], trim: [-60, -10],
  };

  const FAILURE_PARTS = {
    idle_stop_no_restart: ["battery12v", "starter", "ecu"],
    stall_while_moving: ["engine", "fuel", "ecu"],
    wont_start_when_parked: ["battery12v", "starter"],
    unintended_acceleration: ["pedals", "ecu", "sensors"],
    brake_failure: ["brakes"],
    stuck_gear_or_rollaway: ["transmission", "shifter"],
    steering_assist_loss: ["steering"],
    pull_shake_or_vibration: ["suspension", "wheels"],
    unwanted_driver_assist: ["sensors", "ecu"],
    restraint_fault: ["restraints"],
    fire_smoke_or_burning: ["harness", "battery12v"],
    leak: ["engine", "cooling", "fuel"],
    wheel_or_tire: ["wheels"],
    body_or_latch: ["latches", "trim"],
    lighting_or_visibility: ["lights", "wipers"],
    other: [],
  };

  const FILED_PARTS = [
    [/^ENGINE AND ENGINE COOLING/, ["engine", "cooling"]],
    [/^ENGINE/, ["engine"]],
    [/^ELECTRICAL/, ["harness"]],
    [/^POWER TRAIN/, ["transmission"]],
    [/^STEERING/, ["steering"]],
    [/BRAKE/, ["brakes"]],
    [/^FUEL/, ["fuel"]],
    [/^HYBRID PROPULSION/, ["pack"]],
    [/COLLISION|LANE|BACK OVER|ADAPTIVE|DRIVER ASSIST/, ["sensors"]],
    [/^STRUCTURE/, ["trim"]],
    [/^AIR BAGS|^SEAT BELTS/, ["restraints"]],
    [/^SEATS/, ["seats"]],
    [/^EXTERIOR LIGHTING|^LIGHTING/, ["lights"]],
    [/^VISIBILITY/, ["wipers"]],
    [/^SUSPENSION/, ["suspension"]],
    [/^WHEELS|^TIRES/, ["wheels"]],
    [/^VEHICLE SPEED CONTROL|^ACCELERATOR/, ["pedals"]],
    [/^LATCHES/, ["latches"]],
  ];

  const EV_SWAP = { engine: "motor", fuel: "pack", starter: null, exhaust: null };

  function forPowertrain(keys, powertrain) {
    if (powertrain !== "ev") return keys;
    return keys.map((key) => (key in EV_SWAP ? EV_SWAP[key] : key)).filter(Boolean);
  }

  function describedParts(failure, powertrain) {
    return [...new Set(forPowertrain(FAILURE_PARTS[failure] || [], powertrain))];
  }

  function failuresForPart(key) {
    return Object.keys(FAILURE_PARTS).filter(
      (failure) =>
        describedParts(failure, "ice").includes(key) || describedParts(failure, "ev").includes(key)
    );
  }

  function filedParts(filed, powertrain) {
    const byPart = new Map();
    const unmapped = [];
    for (const item of filed || []) {
      const rule = FILED_PARTS.find(([pattern]) => pattern.test(item.name));
      if (!rule) {
        unmapped.push(item);
        continue;
      }
      for (const key of forPowertrain(rule[1], powertrain)) {
        const entry = byPart.get(key) || { key, count: 0, codes: [] };
        entry.count += item.count;
        entry.codes.push(item);
        byPart.set(key, entry);
      }
    }
    return { parts: [...byPart.values()].sort((a, b) => b.count - a.count), unmapped };
  }

  const n = (value) => Math.round(value * 10) / 10;

  function roundedPath(points, radius) {
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 1; i < points.length - 1; i++) {
      const [x0, y0] = points[i - 1];
      const [x1, y1] = points[i];
      const [x2, y2] = points[i + 1];
      const l1 = Math.hypot(x1 - x0, y1 - y0);
      const l2 = Math.hypot(x2 - x1, y2 - y1);
      const r = Math.min(radius, l1 / 2, l2 / 2);
      d += ` L${n(x1 + ((x0 - x1) * r) / l1)},${n(y1 + ((y0 - y1) * r) / l1)}`;
      d += ` Q${x1},${y1} ${n(x1 + ((x2 - x1) * r) / l2)},${n(y1 + ((y2 - y1) * r) / l2)}`;
    }
    const last = points[points.length - 1];
    return `${d} L${last[0]},${last[1]}`;
  }

  function outlinePath(b) {
    const cy = GROUND - b.r;
    const R = b.r + 9;
    const a = Math.sqrt(R * R - (cy - b.sill) ** 2);
    let d = roundedPath(b.pts, 16);
    d += ` L${n(b.rx + a)},${b.sill} A${R},${R} 0 0 0 ${n(b.rx - a)},${b.sill}`;
    d += ` L${n(b.fx + a)},${b.sill} A${R},${R} 0 0 0 ${n(b.fx - a)},${b.sill} Z`;
    return d;
  }

  function coil(x, top, bottom, turns, width) {
    const step = (bottom - top) / (turns * 2);
    let d = `M${x},${n(top)}`;
    for (let i = 1; i <= turns * 2; i++) {
      d += ` L${n(x + (i % 2 ? width / 2 : -width / 2))},${n(top + step * i)}`;
    }
    return `${d} L${x},${n(bottom)}`;
  }

  function build(type, powertrain) {
    const b = BODIES[type] || BODIES.crossover;
    const p = b.pts;
    const ev = powertrain === "ev";
    const cowl = p[b.cowl];
    const ws = p[b.ws];
    const roof = p[b.roof];
    const rear = p[b.rear];
    const hood = p[2];
    const nose = p[0][0];
    const tail = p[p.length - 1][0];
    const tailTop = p[p.length - 2];
    const { r, fx, rx, sill } = b;
    const cy = GROUND - r;
    const belt = cowl[1];
    const floor = sill - 14;
    const bayTop = hood[1] + 16;
    const bayBot = cy + 6;
    const span = roof[0] - ws[0];
    const roofY = (x) => ws[1] + (roof[1] - ws[1]) * ((x - ws[0]) / span);
    const parts = [];
    const add = (key, svg) => parts.push({ key, svg });

    // Shell
    let t = (belt - roof[1]) / (rear[1] - roof[1]);
    t = Math.min(1, Math.max(0, t));
    const rearBeltX = roof[0] + t * (rear[0] - roof[0]) - 18;
    const dividers = b.pillars.map((f) => ws[0] + span * f);
    const edges = [null, ...dividers, null];
    let glass = "";
    for (let i = 0; i < edges.length - 1; i++) {
      const left = edges[i];
      const right = edges[i + 1];
      const pts = [];
      if (left === null) pts.push([cowl[0] + 20, belt - 2], [ws[0] + 10, ws[1] + 12]);
      else pts.push([left + 7, belt - 2], [left + 7, roofY(left + 7) + 12]);
      if (right === null) pts.push([roof[0] - 12, roof[1] + 12], [rearBeltX, belt - 2]);
      else pts.push([right - 7, roofY(right - 7) + 12], [right - 7, belt - 2]);
      glass += `<polygon class="glass" points="${pts.map(([x, y]) => `${n(x)},${n(y)}`).join(" ")}"/>`;
    }
    const doorLines = [cowl[0] + 8, ...dividers]
      .map((x, i) => `<line class="thin" x1="${n(x)}" y1="${belt}" x2="${n(x + (i === 0 ? 6 : 0))}" y2="${sill - 6}"/>`)
      .join("");
    const bed = b.bed
      ? `<path class="thin" d="M${rear[0] + 8},${p[b.rear + 1][1] + 10} H${tail - 10} M${tail - 18},${p[b.rear + 1][1]} V${sill - 4}"/>`
      : "";
    add(
      "body",
      `${glass}<path class="shell" pathLength="1" d="${outlinePath(b)}"/>
       ${doorLines}${bed}
       <line class="thin" x1="${cowl[0]}" y1="${belt + 2}" x2="${n(Math.min(rear[0], tail - 20))}" y2="${belt + 2}"/>
       <line class="thin" x1="${n(fx + r + 14)}" y1="${sill - 10}" x2="${n(rx - r - 14)}" y2="${sill - 10}"/>`
    );

    // Floor-level systems
    if (ev) {
      const x0 = fx + r + 8;
      const x1 = rx - r - 8;
      let modules = "";
      for (let x = x0 + 44; x < x1 - 10; x += 44) {
        modules += `<line class="thin" x1="${x}" y1="${GROUND - 54}" x2="${x}" y2="${GROUND - 38}"/>`;
      }
      add("pack", `<rect class="ht" x="${x0}" y="${GROUND - 56}" width="${x1 - x0}" height="20" rx="3"/>${modules}`);
    } else {
      const tx0 = rx - r - 130;
      const tx1 = rx - r - 16;
      add(
        "fuel",
        `<rect class="sf" x="${tx0}" y="${floor - 4}" width="${tx1 - tx0}" height="${GROUND - 40 - floor + 4}" rx="10"/>
         <path class="ln" d="M${tx1 - 8},${floor} C${tx1 + 20},${floor - 10} ${rx + r - 20},${belt + 40} ${rx + r - 6},${belt + 18}"/>
         <path class="dl" d="M${tx0},${GROUND - 46} H${fx + 60} L${fx + 30},${bayBot}"/>`
      );
      const ex0 = fx - 34;
      const mx = rx + r + 6;
      add(
        "exhaust",
        `<path class="ln pipe" d="M${ex0 + 30},${bayBot} C${ex0 + 36},${GROUND - 24} ${ex0 + 60},${GROUND - 30} ${ex0 + 90},${GROUND - 30} H${mx}"/>
         <rect class="sf" x="${mx}" y="${GROUND - 40}" width="62" height="18" rx="8"/>
         <path class="ln pipe" d="M${mx + 62},${GROUND - 31} H${tail - 8}"/>`
      );
    }

    const harness = `M${nose + 62},${bayTop + 26} L${cowl[0] - 2},${bayTop + 30} L${cowl[0] + 6},${floor - 2} L${tail - 46},${floor - 2} L${tailTop[0] - 6},${tailTop[1] + 14}`;
    add("harness", `<path class="harness" d="${harness}"/><path class="harness" d="M${nose + 62},${bayTop + 26} L${hood[0] + 18},${hood[1] + 12}"/>`);

    // Cabin
    const seatSpan = rear[0] - ws[0];
    let seats = "";
    b.seats.forEach((f) => {
      const sx = ws[0] + seatSpan * f;
      seats += `<path class="sf" d="M${n(sx - 64)},${floor - 24} H${n(sx)} V${floor - 12} H${n(sx - 60)} Z"/>
        <path class="sf" d="M${n(sx - 6)},${floor - 22} L${n(sx + 6)},${belt - 34} L${n(sx + 20)},${belt - 32} L${n(sx + 8)},${floor - 20} Z"/>
        <rect class="sf" x="${n(sx + 6)}" y="${belt - 52}" width="14" height="14" rx="3"/>`;
    });
    add("seats", seats);

    const sx = cowl[0] + 60;
    const sy = belt + 6;
    add(
      "steering",
      `<line class="ln" x1="${sx + 2}" y1="${sy + 4}" x2="${cowl[0] - 6}" y2="${bayBot - 14}"/>
       <ellipse class="sf" cx="${sx}" cy="${sy}" rx="6" ry="22" transform="rotate(-28 ${sx} ${sy})"/>
       <rect class="sf" x="${fx + 12}" y="${bayBot - 20}" width="50" height="9" rx="4"/>
       <circle class="ht" cx="${fx + 44}" cy="${bayBot - 26}" r="7"/>
       <line class="ln" x1="${fx + 12}" y1="${bayBot - 15}" x2="${fx}" y2="${cy - 6}"/>`
    );

    add(
      "pedals",
      `<path class="ln" d="M${cowl[0] + 14},${floor - 30} L${cowl[0] + 26},${floor - 8} M${cowl[0] + 20},${floor - 10} l12,-3"/>
       <path class="ln" d="M${cowl[0] + 30},${floor - 32} L${cowl[0] + 40},${floor - 10} M${cowl[0] + 34},${floor - 12} l11,-3"/>`
    );

    add(
      "shifter",
      `<path class="sf" d="M${cowl[0] + 112},${floor - 4} h28 l-6,-12 h-16 z"/>
       <line class="ln" x1="${cowl[0] + 126}" y1="${floor - 16}" x2="${cowl[0] + 120}" y2="${floor - 38}"/>
       <circle class="sf" cx="${cowl[0] + 119}" cy="${floor - 42}" r="5"/>`
    );

    add(
      "ecu",
      `<rect class="ht" x="${cowl[0] + 12}" y="${belt + 22}" width="26" height="16" rx="2"/>
       <path class="thin" d="M${cowl[0] + 16},${belt + 38} v5 M${cowl[0] + 22},${belt + 38} v5 M${cowl[0] + 28},${belt + 38} v5 M${cowl[0] + 34},${belt + 38} v5"/>`
    );

    const firstSeat = ws[0] + seatSpan * b.seats[0];
    add(
      "restraints",
      `<ellipse class="dl" cx="${sx - 14}" cy="${sy - 6}" rx="13" ry="17"/>
       <path class="dl" d="M${ws[0] + 16},${n(ws[1] + 20)} L${roof[0] - 16},${n(roof[1] + 20)}"/>
       <line class="ln" x1="${n(firstSeat + 12)}" y1="${belt - 30}" x2="${n(firstSeat - 44)}" y2="${floor - 24}"/>`
    );

    // Engine bay / drive units
    if (ev) {
      const m1 = fx + r + 22;
      const m2 = rx - r - 22;
      add(
        "motor",
        `<rect class="ht" x="${m1 - 28}" y="${cy - 30}" width="56" height="40" rx="8"/>
         <circle class="sf" cx="${m1}" cy="${cy - 10}" r="11"/>
         <rect class="ht" x="${m2 - 30}" y="${cy - 32}" width="60" height="44" rx="8"/>
         <circle class="sf" cx="${m2}" cy="${cy - 10}" r="12"/>`
      );
      add(
        "transmission",
        `<circle class="sf" cx="${m2 + 36}" cy="${cy - 14}" r="10"/><circle class="sf" cx="${m2 + 44}" cy="${cy + 2}" r="7"/>`
      );
      add(
        "driveline",
        `<line class="ln shaft" x1="${m1 - 28}" y1="${cy - 4}" x2="${fx}" y2="${cy}"/>
         <line class="ln shaft" x1="${m2 + 44}" y1="${cy + 2}" x2="${rx}" y2="${cy}"/>`
      );
    } else {
      const ex0 = fx - 34;
      const ex1 = Math.min(cowl[0] - 20, fx + 120);
      const w = ex1 - ex0;
      const bore = (w - 24) / 4;
      let bores = "";
      for (let i = 0; i < 4; i++) {
        bores += `<rect class="sf" x="${n(ex0 + 12 + i * bore + 3)}" y="${bayTop + 22}" width="${n(bore - 6)}" height="${n((bayBot - bayTop) * 0.42)}" rx="3"/>`;
      }
      add(
        "engine",
        `<rect class="ht" x="${ex0}" y="${bayTop + 14}" width="${w}" height="${bayBot - bayTop - 14}" rx="4"/>
         <rect class="sf" x="${ex0 + 10}" y="${bayTop}" width="${w - 20}" height="16" rx="3"/>
         ${bores}
         <circle class="sf" cx="${ex0 - 2}" cy="${bayBot - 14}" r="9"/>
         <path class="ln" d="M${ex1 - 14},${bayTop + 2} C${ex1 + 6},${bayTop - 12} ${ex0 + 40},${bayTop - 14} ${ex0 + 24},${bayTop + 2}"/>`
      );
      const rwd = type === "pickup" || type === "suv";
      if (rwd) {
        add(
          "transmission",
          `<path class="ht" d="M${ex1},${bayBot - 50} L${ex1 + 30},${bayBot - 44} L${ex1 + 120},${bayBot - 24} L${ex1 + 120},${bayBot - 6} L${ex1},${bayBot - 2} Z"/>`
        );
        add(
          "driveline",
          `<line class="ln shaft" x1="${ex1 + 120}" y1="${bayBot - 14}" x2="${rx - 14}" y2="${cy}"/>
           <circle class="sf" cx="${rx}" cy="${cy}" r="14"/>`
        );
      } else {
        add(
          "transmission",
          `<path class="ht" d="M${ex1 - 44},${bayBot - 34} H${ex1 + 18} L${ex1 + 28},${bayBot - 12} L${ex1 + 18},${bayBot - 2} H${ex1 - 44} Z"/>`
        );
        add("driveline", `<line class="ln shaft" x1="${ex1 - 40}" y1="${bayBot - 16}" x2="${fx}" y2="${cy}"/>`);
      }
      add(
        "starter",
        `<rect class="sf" x="${ex1 - 38}" y="${bayBot}" width="30" height="13" rx="6"/><line class="thin" x1="${ex1 - 30}" y1="${bayBot}" x2="${ex1 - 30}" y2="${bayBot + 13}"/>`
      );
    }

    let fins = "";
    for (let y = bayTop + 10; y < bayBot - 14; y += 6) {
      fins += `<line class="thin" x1="${nose + 20}" y1="${y}" x2="${nose + 32}" y2="${y}"/>`;
    }
    add(
      "cooling",
      `<rect class="sf" x="${nose + 20}" y="${bayTop + 4}" width="12" height="${bayBot - bayTop - 14}"/>${fins}
       <path class="ln" d="M${nose + 32},${bayTop + 10} C${nose + 60},${bayTop} ${fx - 70},${bayTop + 30} ${fx - 36},${bayTop + 26}"/>`
    );

    add(
      "battery12v",
      `<rect class="sf" x="${nose + 44}" y="${bayTop + 2}" width="36" height="24" rx="2"/>
       <rect class="sf" x="${nose + 49}" y="${bayTop - 3}" width="7" height="5"/>
       <rect class="sf" x="${nose + 68}" y="${bayTop - 3}" width="7" height="5"/>
       <path class="thin" d="M${nose + 50},${bayTop + 14} h6 M${nose + 53},${bayTop + 11} v6 M${nose + 68},${bayTop + 14} h6"/>`
    );

    // Running gear
    let wheels = "";
    let brakes = "";
    let springs = "";
    for (const x of [fx, rx]) {
      let lugs = "";
      for (let i = 0; i < 5; i++) {
        const a = (Math.PI * 2 * i) / 5 - Math.PI / 2;
        lugs += `<circle class="dot" cx="${n(x + Math.cos(a) * r * 0.24)}" cy="${n(cy + Math.sin(a) * r * 0.24)}" r="1.8"/>`;
      }
      wheels += `<circle class="sf tire" cx="${x}" cy="${cy}" r="${r}"/>
        <circle class="thin" cx="${x}" cy="${cy}" r="${r - 9}"/>
        <circle class="ln" cx="${x}" cy="${cy}" r="${n(r * 0.62)}"/>
        <circle class="sf" cx="${x}" cy="${cy}" r="7"/>${lugs}`;
      const dr = r * 0.5;
      const a0 = (-150 * Math.PI) / 180;
      const a1 = (-95 * Math.PI) / 180;
      const cr = dr + 3;
      brakes += `<circle class="ht" cx="${x}" cy="${cy}" r="${n(dr)}"/>
        <circle class="dl" cx="${x}" cy="${cy}" r="${n(dr * 0.5)}"/>
        <path class="caliper" d="M${n(x + Math.cos(a0) * cr)},${n(cy + Math.sin(a0) * cr)} A${n(cr)},${n(cr)} 0 0 1 ${n(x + Math.cos(a1) * cr)},${n(cy + Math.sin(a1) * cr)}"/>`;
      springs += `<line class="thin" x1="${x}" y1="${cy}" x2="${x}" y2="${cy - r - 18}"/>
        <path class="ln" d="${coil(x, cy - r - 6, cy - 10, 6, 18)}"/>
        <rect class="sf" x="${x - 12}" y="${cy - r - 22}" width="24" height="6" rx="2"/>`;
    }
    brakes += `<rect class="sf" x="${cowl[0] - 26}" y="${bayTop + 2}" width="22" height="12" rx="2"/>
      <rect class="sf" x="${cowl[0] - 22}" y="${bayTop - 6}" width="12" height="8" rx="2"/>
      <path class="dl" d="M${cowl[0] - 15},${bayTop + 14} L${cowl[0] - 8},${floor + 6} H${rx - 10} L${rx - 6},${n(cy - r * 0.5)} M${cowl[0] - 12},${bayTop + 20} L${fx + 8},${n(cy - r * 0.5)}"/>`;
    add("wheels", wheels);
    add("brakes", brakes);
    add("suspension", springs);

    // Exterior details
    add(
      "lights",
      `<path class="sf" d="M${hood[0] - 2},${hood[1] + 6} L${hood[0] + 34},${hood[1] + 2} L${hood[0] + 30},${hood[1] + 14} L${hood[0] - 4},${hood[1] + 16} Z"/>
       <path class="beam" d="M${hood[0] - 8},${hood[1] + 8} L${nose - 56},${hood[1] - 2} M${hood[0] - 8},${hood[1] + 12} L${nose - 60},${hood[1] + 12} M${hood[0] - 8},${hood[1] + 16} L${nose - 56},${hood[1] + 26}"/>
       <rect class="sf" x="${tailTop[0] - 10}" y="${tailTop[1] + 4}" width="8" height="20" rx="1"/>`
    );

    add(
      "sensors",
      `<rect class="sf" x="${ws[0] - 6}" y="${ws[1] + 12}" width="16" height="10" rx="2"/>
       <circle class="ln" cx="${ws[0] - 1}" cy="${ws[1] + 17}" r="2.5"/>
       <rect class="sf" x="${nose + 2}" y="${bayBot - 44}" width="8" height="18" rx="2"/>
       <path class="beam" d="M${nose - 6},${bayBot - 44} q-10,9 0,18 M${nose - 14},${bayBot - 48} q-16,13 0,26 M${nose - 22},${bayBot - 52} q-22,17 0,34"/>
       <circle class="sf" cx="${tail - 6}" cy="${tailTop[1] + 36}" r="4"/>`
    );

    const wdx = ws[0] - cowl[0];
    const wdy = ws[1] - cowl[1];
    const wl = Math.hypot(wdx, wdy);
    add(
      "wipers",
      `<line class="wiper" x1="${cowl[0] + 10}" y1="${belt - 4}" x2="${n(cowl[0] + 10 + (wdx / wl) * 62)}" y2="${n(belt - 4 + (wdy / wl) * 62)}"/>
       <circle class="sf" cx="${cowl[0] + 10}" cy="${belt - 4}" r="3"/>`
    );

    const handles = [cowl[0] + 8, ...dividers]
      .map((x) => `<rect class="sf" x="${n(x + 26)}" y="${belt + 14}" width="18" height="4" rx="2"/>`)
      .join("");
    add("latches", `${handles}<rect class="sf" x="${nose + 10}" y="${hood[1] + 2}" width="10" height="6" rx="1"/>`);

    let slats = "";
    for (let x = nose + 3; x <= nose + 15; x += 4) {
      slats += `<line class="thin" x1="${x}" y1="${hood[1] + 22}" x2="${x}" y2="${bayBot - 50}"/>`;
    }
    add(
      "trim",
      `${slats}
       <path class="ln" d="M${nose - 2},${bayBot - 22} Q${nose + 4},${sill + 2} ${nose + 44},${sill - 2}"/>
       <path class="ln" d="M${tail + 2},${bayBot - 22} Q${tail - 4},${sill + 2} ${tail - 44},${sill - 2}"/>
       <path class="sf" d="M${cowl[0] + 16},${belt - 4} l18,-12 h8 v10 z"/>`
    );

    return { parts, geometry: { fx, rx, cy, r } };
  }

  const ORDER = [
    "pack", "fuel", "exhaust", "harness", "driveline", "seats", "pedals", "shifter",
    "motor", "engine", "transmission", "starter", "cooling", "battery12v", "ecu",
    "steering", "restraints", "wheels", "brakes", "suspension", "lights", "sensors",
    "wipers", "latches", "trim", "body",
  ];

  function markup(type, powertrain) {
    const { parts, geometry } = build(type, powertrain);
    const byKey = new Map(parts.map((part) => [part.key, part]));
    const groups = ORDER.filter((key) => byKey.has(key))
      .map((key, i) => {
        const [dx, dy] = EXPLODE[key] || [0, 0];
        return `<g class="part" data-key="${key}" style="--dx:${dx}px;--dy:${dy}px;--i:${i}">
          <title>${LABELS[key]}</title>${byKey.get(key).svg}</g>`;
      })
      .join("");
    const { fx, rx } = geometry;
    return `<svg class="cutaway" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Cutaway drawing">
      <defs>
        <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" class="hatch-line"/>
        </pattern>
        <pattern id="hatch-dark" width="3.2" height="3.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="3.2" height="3.2" class="hatch-dark-bg"/>
          <line x1="0" y1="0" x2="0" y2="3.2" class="hatch-dark-line"/>
        </pattern>
        <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
          <path d="M20 0H0V20" class="grid-line"/>
        </pattern>
      </defs>
      <rect width="${W}" height="${H}" fill="url(#grid)"/>
      <g class="sheet">
        <line class="ground" x1="20" y1="${GROUND}" x2="${W - 20}" y2="${GROUND}"/>
        <g class="dimension">
          <line x1="${fx}" y1="${GROUND + 8}" x2="${fx}" y2="${GROUND + 36}"/>
          <line x1="${rx}" y1="${GROUND + 8}" x2="${rx}" y2="${GROUND + 36}"/>
          <line x1="${fx}" y1="${GROUND + 28}" x2="${rx}" y2="${GROUND + 28}"/>
          <path d="M${fx},${GROUND + 28} l8,-3 v6 z M${rx},${GROUND + 28} l-8,-3 v6 z"/>
          <text x="${(fx + rx) / 2}" y="${GROUND + 23}">WHEELBASE</text>
        </g>
      </g>
      <g class="axes"></g>
      <g class="parts">${groups}</g>
      <g class="callouts"></g>
    </svg>`;
  }

  function outline(type) {
    const b = BODIES[type] || BODIES.crossover;
    return outlinePath(b);
  }

  window.Cutaway = {
    W, H, GROUND, BODIES, LABELS, markup, outline, describedParts, filedParts, failuresForPart,
  };
})();
