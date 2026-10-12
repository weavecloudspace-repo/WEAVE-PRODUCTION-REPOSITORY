import windowsLogo from "../../assets/platforms/windows.svg";
import linuxLogo from "../../assets/platforms/linux.svg";

const LOGOS = {
  windows: windowsLogo,
  linux: linuxLogo,
};

export default function PlatformLogo({ platform, className = "h-6 w-6" }) {
  return <img src={LOGOS[platform]} alt="" aria-hidden="true" className={"object-contain " + className} />;
}
