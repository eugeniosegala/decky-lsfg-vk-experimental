import { staticClasses } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { GiPlasticDuck } from "react-icons/gi";
import { Content } from "./components/Content";

export default definePlugin(() => {
  console.log("decky-lsfg-vk-v2-preview plugin initializing");

  return {
    name: "Decky LSFG-VK V2 Preview",
    titleView: <div className={staticClasses.Title}>Decky LSFG-VK V2 Preview</div>,
    alwaysRender: true,
    content: <Content />,
    icon: <GiPlasticDuck />,
    onDismount() {
      console.log("decky-lsfg-vk-v2-preview unloading");
    }
  };
});
