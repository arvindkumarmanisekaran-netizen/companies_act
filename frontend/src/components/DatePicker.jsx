import React, { useEffect, useState } from "react";
import { CalendarDays } from "lucide-react";

const isoToDisplay = (value) => {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return match ? `${match[3]}/${match[2]}/${match[1]}` : "";
};

const displayToIso = (value) => {
  const match = String(value || "").match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (!match) return null;
  const iso = `${match[3]}-${match[2]}-${match[1]}`;
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== iso ? null : iso;
};

const maskDate = (value) => {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join("/");
};

export default function DatePicker({ value = "", onChange, min, max, className = "", inputClassName = "", ariaLabel = "Choose date", allowEmpty = false }) {
  const [displayValue, setDisplayValue] = useState(isoToDisplay(value));

  useEffect(() => setDisplayValue(isoToDisplay(value)), [value]);

  const commit = () => {
    if (!displayValue && allowEmpty) return onChange?.("");
    const iso = displayToIso(displayValue);
    if (iso && (!min || iso >= min) && (!max || iso <= max)) onChange?.(iso);
    else setDisplayValue(isoToDisplay(value));
  };

  const updateDisplay = (nextValue) => {
    const masked = maskDate(nextValue);
    setDisplayValue(masked);
    const iso = displayToIso(masked);
    if (iso && (!min || iso >= min) && (!max || iso <= max)) onChange?.(iso);
  };

  return (
    <div className={`date-picker-control relative ${className}`}>
      <input
        type="text"
        inputMode="numeric"
        value={displayValue}
        placeholder="DD/MM/YYYY"
        aria-label={ariaLabel}
        onChange={(event) => updateDisplay(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); commit(); }
        }}
        className={`w-full pr-9 ${inputClassName}`}
      />
      <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-0 z-10 grid w-9 place-items-center rounded-r-lg text-slate-500">
        <CalendarDays size={16}/>
      </span>
      <input
        type="date"
        aria-label={`Open ${ariaLabel.toLowerCase()} calendar`}
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange?.(event.target.value)}
        className="absolute inset-y-0 right-0 z-20 w-9 cursor-pointer opacity-0"
      />
    </div>
  );
}
