import { Children } from "react";
import SearchableSelect from "../../components/ui/SearchableSelect";

// Keep configuration and filter controls on the same accessible, themed picker.
export default function TmaSelect({
  label,
  value,
  onChange,
  children,
  disabled = false,
  placeholder,
  clearable = false,
}) {
  const options = Children.toArray(children)
    .filter(Boolean)
    .map((option) => {
      const text = Children.toArray(option.props.children).join("");
      return {
        value: String(option.props.value ?? text),
        label: text,
        disabled: option.props.disabled,
      };
    });
  return (
    <SearchableSelect
      label={label}
      value={value || ""}
      onChange={onChange}
      options={options}
      disabled={disabled}
      placeholder={placeholder || `Select ${label.toLowerCase()}`}
      clearable={clearable}
    />
  );
}
